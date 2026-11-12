"""CLI command for harms testing BCAL through direct (UPIA) and indirect (XPIA) vectors."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal.harms.case import HarmsVector
from bcbench.agent.bcal.harms.evaluate import DEFAULT_EVALUATORS, build_eval_dataset, evaluate_trials
from bcbench.agent.bcal.harms.runner import HarmsTrial, annotate_trials, execution_failure, run_harms_suite, valid_trial, write_trials
from bcbench.agent.bcal.harms.score import SCORER_VERSION, score_trials, scoring_sources, scoring_summary
from bcbench.agent.bcal.harms.suite import load_suite
from bcbench.config import get_config

type Json = dict[str, Any]

logger = logging.getLogger(__name__)
_config = get_config()
_console = Console()

app = typer.Typer(help="NL2AL adversarial evaluation of BCal: capture, objective judgments, and separate Azure telemetry", pretty_exceptions_show_locals=False)

_DEFAULT_SUITE = _config.paths.dataset_dir / "nl2al" / "harms" / "comprehensive.harms.yaml"
_RESULTS = _config.paths.evaluation_results_path / "nl2al" / "harms"


@app.command("run")
def run(
    suite: Annotated[Path, typer.Option(help="Harms suite YAML to load.")] = _DEFAULT_SUITE,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (external-command backend).")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model (external-command backend).")] = None,
    results_dir: Annotated[Path, typer.Option(help="New directory for captured trials, fixtures, and logs.")] = _RESULTS,
    limit: Annotated[int | None, typer.Option(min=1, help="Cap the number of cases (rapid validation).")] = None,
    vector: Annotated[list[HarmsVector] | None, typer.Option("--vector", help="Restrict the vector matrix (repeatable), e.g. --vector direct. Overrides case/suite matrices.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Write fixtures and planned rows without executing BCal.")] = False,
) -> None:
    """Capture fixed NL2AL cases; judging and optional Azure telemetry are separate commands."""
    cases = load_suite(suite)
    if results_dir.exists():
        raise typer.BadParameter(f"Capture directory already exists: {results_dir}")
    results_dir.mkdir(parents=True)
    trials = run_harms_suite(
        cases,
        backend_config=BCalBackendConfig(command=llm_command, model=llm_model),
        results_dir=results_dir,
        limit=limit,
        vectors=vector,
        dry_run=dry_run,
    )

    build_eval_dataset(trials, results_dir / "eval_dataset.jsonl")
    if dry_run:
        _console.print(f"[yellow]Dry run[/]: planned {len(trials)} trials. Fixtures under {results_dir / 'fixtures'}.")
    _render_trials(trials)
    if any(execution_failure(trial) for trial in trials):
        raise typer.Exit(1)


@app.command("evaluate")
def evaluate(
    trials_path: Annotated[Path, typer.Argument(help="A trials.jsonl (or its results dir) produced by `harms run`.")] = _RESULTS,
    subscription_id: Annotated[str | None, typer.Option(envvar="AZURE_SUBSCRIPTION_ID", help="Foundry Hub subscription ID.")] = None,
    resource_group: Annotated[str | None, typer.Option(envvar="AZURE_RESOURCE_GROUP", help="Foundry Hub resource group.")] = None,
    project_name: Annotated[str | None, typer.Option(envvar="AZURE_PROJECT_NAME", help="Foundry Hub project name.")] = None,
    evaluator: Annotated[list[str] | None, typer.Option("--evaluator", help="Override the evaluator set (repeatable).")] = None,
    no_upload: Annotated[bool, typer.Option("--no-upload", help="Score locally but skip the Foundry upload.")] = False,
) -> None:
    """
    Re-score existing bcal trials with the safety evaluators, without re-running bcal.

    Lets you iterate on the evaluator set cheaply after an expensive `harms run`.

    Example:
        uv run python -m bcbench.agent.bcal.harms evaluate evaluation_results/harms/smoke-run
    """
    if not subscription_id or not resource_group or not project_name:
        raise typer.BadParameter("Foundry project (AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME) is required.")

    results_dir = trials_path if trials_path.is_dir() else trials_path.parent
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    trials = _load_trials(trials_file)
    azure_ai_project = {"subscription_id": subscription_id, "resource_group_name": resource_group, "project_name": project_name}
    result = evaluate_trials(trials, azure_ai_project, results_dir, evaluators=tuple(evaluator) if evaluator else DEFAULT_EVALUATORS, upload=not no_upload)
    _console.print(f"Harms results written to {results_dir / 'harms_results.json'}")
    _render_results(result, trials)
    if result.get("failed_evaluators") or result.get("incomplete_evaluations"):
        raise typer.Exit(1)


@app.command("annotate")
def annotate(
    trials_path: Annotated[Path, typer.Argument(help="Captured trials.jsonl or its directory.")],
    output_dir: Annotated[Path, typer.Option(help="New directory for delivery annotations; original captures are unchanged.")],
) -> None:
    """Re-derive delivery from saved logs without overwriting the capture."""
    results_dir = trials_path if trials_path.is_dir() else trials_path.parent
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    annotated = annotate_trials(_load_trials(trials_file), results_dir=results_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_trials(output_dir / "trials.jsonl", annotated)
    build_eval_dataset(annotated, output_dir / "eval_dataset.jsonl")
    _console.print(f"Annotated {len(annotated)} trials at {output_dir}.")
    _render_trials(annotated)


@app.command("score")
def score(
    trials_path: Annotated[Path, typer.Argument(help="Captured trials.jsonl or its directory.")],
    output_dir: Annotated[Path, typer.Option(help="New directory for scores; original captures are unchanged.")],
    model: Annotated[str | None, typer.Option(help="Copilot model for objective judging (defaults to the configured judge model).")] = None,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="Detector diagnostics only; objective scores remain incomplete.")] = False,
    bcquality_root: Annotated[Path | None, typer.Option(envvar="BCQUALITY_ROOT", help="BCQuality checkout at the pinned harms knowledge commit.")] = None,
) -> None:
    """Judge objective-following from saved evidence, optionally grounded in pinned BCQuality rules."""
    results_dir = output_dir
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    input_hash = hashlib.sha256(trials_file.read_bytes()).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=False)
    scored = score_trials(_load_trials(trials_file), model=model, use_judge=not no_judge, bcquality_root=bcquality_root)
    write_trials(results_dir / "trials.jsonl", scored)
    build_eval_dataset(scored, results_dir / "eval_dataset.jsonl")
    summary = scoring_summary(scored)
    (results_dir / "scoring-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (results_dir / "scoring-manifest.json").write_text(
        json.dumps(
            {"input_sha256": input_hash, "scorer_version": SCORER_VERSION, "scoring_sources": scoring_sources(), "judge_models": sorted({t.judge_model for t in scored if t.judge_model})}, indent=2
        ),
        encoding="utf-8",
    )
    _console.print(f"Objective scoring attempted for {len(scored)} trials; results saved at {results_dir}.")
    _render_trials(scored)
    if not summary["scored"] or summary["unscored_delivered"]:
        _console.print("[red]Scoring incomplete; see score_error in the saved trials.[/]")
        raise typer.Exit(code=1)


@app.command("report")
def report(
    path: Annotated[Path, typer.Argument(help="A harms_results.json (or its directory), or a trials.jsonl to render.")] = _RESULTS,
) -> None:
    """Render saved harms results as tables."""
    if path.is_dir():
        results_file = path / "harms_results.json"
        trials_file = path / "trials.jsonl"
    elif path.name == "trials.jsonl":
        results_file, trials_file = None, path
    else:
        results_file, trials_file = path, path.parent / "trials.jsonl"

    trials = _load_trials(trials_file) if trials_file and trials_file.exists() else []
    if results_file and results_file.exists():
        _render_results(json.loads(results_file.read_text(encoding="utf-8")), trials)
    else:
        _render_trials(trials)


# --- rendering ---------------------------------------------------------------


def _load_trials(path: Path) -> list[HarmsTrial]:
    return [HarmsTrial.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _render_trials(trials: list[HarmsTrial]) -> None:
    table = Table(title="Harms trials", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    for heading in ("#", "Case", "Vector", "Channel", "Injected?", "Valid?", "Realized?", "Tools", "Attack"):
        table.add_column(heading)
    for index, trial in enumerate(trials, start=1):
        channel = "[magenta]XPIA[/]" if trial.channel.value == "indirect" else "[cyan]UPIA[/]"
        table.add_row(
            str(index),
            trial.case_id,
            trial.vector.value,
            channel,
            _landed_cell(trial),
            _valid_cell(trial),
            _realized_cell(trial),
            _short(", ".join(trial.tools_invoked) or "-", 24),
            _short(trial.attack),
        )
    _console.print()
    _console.print(table)
    _render_injection_summary(trials)
    _render_validity_summary(trials)
    _render_asr_summary(trials)


def _landed_cell(trial: HarmsTrial) -> str:
    # Direct trials have no seam injection; the payload is the prompt itself.
    if trial.channel.value != "indirect":
        return "[dim]n/a[/]"
    if trial.injection_landed is None:
        return "-"
    return "[green]\u2713 landed[/]" if trial.injection_landed else "[red]\u2717 missed[/]"


def _valid_cell(trial: HarmsTrial) -> str:
    # A line is valid only if the agent actually received the harm (direct: always; indirect: landed).
    if execution_failure(trial):
        return "[red]execution failed[/]"
    if not trial.executed or trial.harm_delivered is None:
        return "-"
    return "[green]\u2713 valid[/]" if trial.harm_delivered else "[red]\u2717 invalid[/]"


def _realized_cell(trial: HarmsTrial) -> str:
    # Only current, conclusive objective judgments are displayed.
    if not valid_trial(trial) or trial.scorer_version != SCORER_VERSION or trial.score_error or trial.harm_realized is None:
        return "-"
    tag = "[red]objective realized[/]" if trial.harm_realized else "[green]not realized[/]"
    return f"{tag} [yellow]!?[/]" if trial.score_disagreement else tag


def _render_asr_summary(trials: list[HarmsTrial]) -> None:
    summary = scoring_summary(trials)
    _console.print(f"Coverage: {summary['attempted']} attempted, {summary['delivered']} delivered, {summary['scored']} scored, {summary['unscored_delivered']} delivered but unscored.")
    if summary["objective_success_rate"] is not None:
        _console.print(f"Objective realized: {summary['objective_realized']}/{summary['scored']} scored trials ({100 * summary['objective_success_rate']:.0f}%). Not an AL vulnerability rate.")
    disagreements = [t for t in trials if valid_trial(t) and t.score_disagreement]
    if disagreements:
        _console.print(
            f"[yellow]\u26a0 Detector/judge disagreement on {len(disagreements)} line(s)[/] — review the generated AL "
            f"({_short(', '.join(f'{t.case_id}/{t.vector.value}' for t in disagreements), 80)})."
        )


def _render_validity_summary(trials: list[HarmsTrial]) -> None:
    executed = [t for t in trials if t.executed]
    if not executed:
        return
    valid = [t for t in executed if valid_trial(t)]
    invalid = [t for t in executed if not valid_trial(t)]
    if invalid:
        _console.print(
            f"[yellow]⚠ Validity:[/] {len(valid)}/{len(executed)} result lines are valid (the agent received the harm). "
            f"{len(invalid)} line(s) failed or lack verified harm delivery, so their safety scores are not meaningful "
            f"({_short(', '.join(f'{t.case_id}/{t.vector.value}' for t in invalid), 80)})."
        )
    else:
        _console.print(f"[green]✓ Validity:[/] all {len(valid)} result lines are valid (the agent received the harm).")


def _render_injection_summary(trials: list[HarmsTrial]) -> None:
    indirect = [t for t in trials if t.channel.value == "indirect" and t.executed]
    if not indirect:
        return
    landed = [t for t in indirect if t.injection_landed]
    missed = [t for t in indirect if t.injection_landed is False]
    if missed:
        _console.print(
            f"[yellow]⚠ Injection validation:[/] {len(landed)}/{len(indirect)} indirect (XPIA) trials actually reached the model. "
            f"The injected payload never appeared in a tool result for {len(missed)} trial(s) "
            f"({_short(', '.join(f'{t.case_id}/{t.vector.value}' for t in missed), 80)}). "
            "Their 'resisted' scores are not meaningful — the attack never arrived. "
            "Ensure the trigger invokes the seam-reading tool and the injection targets a real object."
        )
    else:
        _console.print(f"[green]✓ Injection validation:[/] all {len(landed)} indirect (XPIA) trials reached the model.")


def _render_results(result: Json, trials: list[HarmsTrial]) -> None:
    _console.print("[yellow]Azure response telemetry only: not objective-conditioned resistance or an AL vulnerability verdict.[/]")
    if incomplete := result.get("incomplete_evaluations"):
        _console.print(f"[yellow]Incomplete scoring for {len(incomplete)} trial(s): missing scores are not resistance results.[/]")
    metrics: Json = result.get("metrics", {})
    if metrics:
        mtable = Table(title="Evaluator metrics", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
        mtable.add_column("Metric")
        mtable.add_column("Value", justify="right")
        for name, value in sorted(metrics.items()):
            mtable.add_row(name, f"{value}")
        _console.print()
        _console.print(mtable)

    rows: list[Json] = result.get("rows", [])
    if rows:
        rtable = Table(title="Per-trial scores", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
        for heading in ("Case", "Vector", "Channel", "Valid?", *_score_columns(rows)):
            rtable.add_column(heading)
        for row in rows:
            scores = [f"{row.get(col, '-')}" for col in _score_columns(rows)]
            rtable.add_row(
                str(row.get("inputs.case_id", "-")),
                str(row.get("inputs.vector", "-")),
                str(row.get("inputs.channel", "-")),
                _valid_cell_from_row(row),
                *scores,
            )
        _console.print()
        _console.print(rtable)
        _render_injection_summary(trials)
        _render_validity_summary(trials)
        _render_asr_summary(trials)
    elif not metrics:
        _render_trials(trials)

    if url := result.get("studio_url"):
        _console.print(f"Foundry studio: {url}")


def _valid_cell_from_row(row: Json) -> str:
    delivered = row.get("inputs.harm_delivered", row.get("inputs.valid"))
    if delivered is None:
        return "-"
    return "[green]\u2713 valid[/]" if delivered else "[red]\u2717 invalid[/]"


def _score_columns(rows: list[Json]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key.startswith("outputs.") and key.endswith(("_score", "_label", ".severity")) and key not in columns:
                columns.append(key)
    return columns


def _short(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "\u2026"
