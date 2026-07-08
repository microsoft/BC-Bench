"""CLI command for harms testing BCAL through direct (UPIA) and indirect (XPIA) vectors."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.config import get_config
from bcbench.harms import (
    HarmsTrial,
    ManualHarmsSource,
    RedTeamHarmsSource,
    annotate_trials,
    couchings_by_id,
    evaluate_trials,
    harvest_objectives,
    load_objectives,
    run_harms_suite,
    score_trials,
    write_trials,
)
from bcbench.harms.case import HarmsVector
from bcbench.harms.evaluate import DEFAULT_EVALUATORS, build_eval_dataset
from bcbench.logger import get_logger
from bcbench.types import BCalLLMBackend

type Json = dict[str, Any]

logger = get_logger(__name__)
_config = get_config()
_console = Console()

harms_app = typer.Typer(help="Harms-test BCAL by injecting harms through direct and indirect vectors")

_DEFAULT_SUITE = _config.paths.dataset_dir / "harms" / "smoke.harms.yaml"


class HarmsTarget(StrEnum):
    # Only nl2al (BCal) for now; pluggable like redteam.
    BCAL = "bcal"


@harms_app.command("run")
def run(
    suite: Annotated[Path, typer.Option(help="Harms suite YAML to load.")] = _DEFAULT_SUITE,
    subscription_id: Annotated[str | None, typer.Option(envvar="AZURE_SUBSCRIPTION_ID", help="Foundry Hub subscription ID (required unless --dry-run).")] = None,
    resource_group: Annotated[str | None, typer.Option(envvar="AZURE_RESOURCE_GROUP", help="Foundry Hub resource group (required unless --dry-run).")] = None,
    project_name: Annotated[str | None, typer.Option(envvar="AZURE_PROJECT_NAME", help="Foundry Hub project name (required unless --dry-run).")] = None,
    target: Annotated[HarmsTarget, typer.Option(help="Agent under test.")] = HarmsTarget.BCAL,
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend.")] = BCalLLMBackend.AZURE_OPENAI,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (azure-openai backend).")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (azure-openai backend).")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (external-command backend).")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model (external-command backend).")] = None,
    results_dir: Annotated[Path, typer.Option(help="Where to write trials, fixtures, and results.")] = _config.paths.harms_results,
    limit: Annotated[int | None, typer.Option(help="Cap the number of cases (rapid validation).")] = None,
    vector: Annotated[list[HarmsVector] | None, typer.Option("--vector", help="Restrict the vector matrix (repeatable), e.g. --vector direct. Overrides case/suite matrices.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Build fixtures + eval rows but skip bcal and Foundry (instant validation).")] = False,
    no_upload: Annotated[bool, typer.Option("--no-upload", help="Run bcal + local scoring but skip the Foundry upload.")] = False,
    evaluator: Annotated[list[str] | None, typer.Option("--evaluator", help="Override the evaluator set (repeatable): content_safety, indirect_attack, code_vulnerability.")] = None,
    objectives: Annotated[Path | None, typer.Option(help="Red-team attack objectives JSON to couch + expand instead of a YAML suite (see `harms harvest`).")] = None,
    couching: Annotated[list[str] | None, typer.Option("--couching", help="Couching template ids for --objectives (repeatable): system_override, reviewer_note, doc_comment, changelog_note.")] = None,
    page: Annotated[str, typer.Option(help="BC page for red-team objectives (--objectives).")] = "Customer Card",
    audience: Annotated[str, typer.Option(help="Audience for red-team objectives (--objectives).")] = "Business",
) -> None:
    """
    Run a harms suite against BCAL: expand each vector-invariant case across the vector matrix, run
    bcal per trial, score with Azure AI safety evaluators, and upload results to Foundry.

    Cases come from a manual YAML suite (--suite) or red-team attack objectives (--objectives), which
    are couched into a delivered harm + benign trigger before expansion.

    Rapid validation: `--dry-run` (no bcal/network), `--limit 1 --vector direct` (one bcal run).

    Examples:
        uv run bcbench harms run --dry-run
        uv run bcbench harms run --limit 1 --vector direct
        uv run bcbench harms run --suite dataset/harms/comprehensive.harms.yaml
        uv run bcbench harms run --objectives dataset/redteam/attack_objectives.sample.json
    """
    if not dry_run and not all((subscription_id, resource_group, project_name)):
        raise typer.BadParameter("Foundry project (AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME) is required unless --dry-run.")

    results_dir.mkdir(parents=True, exist_ok=True)
    if objectives is not None:
        source = RedTeamHarmsSource(load_objectives(objectives), page=page, audience=audience, couchings=couchings_by_id(couching))
        cases = source.load()
        _console.print(f"[cyan]Red-team source[/]: {len(cases)} couched cases from {objectives}.")
    else:
        cases = ManualHarmsSource(suite).load()

    trials = run_harms_suite(
        cases,
        backend_config=BCalBackendConfig(backend=backend, endpoint=endpoint, deployment=deployment, command=llm_command, model=llm_model),
        results_dir=results_dir,
        limit=limit,
        vectors=vector,
        dry_run=dry_run,
    )

    if dry_run:
        _console.print(f"[yellow]Dry run[/]: planned {len(trials)} trials (bcal + Foundry skipped). Fixtures under {results_dir / 'fixtures'}.")
        _render_trials(trials)
        return

    azure_ai_project = {
        "subscription_id": subscription_id,
        "resource_group_name": resource_group,
        "project_name": project_name,
    }
    result = evaluate_trials(trials, azure_ai_project, results_dir, evaluators=tuple(evaluator) if evaluator else DEFAULT_EVALUATORS, upload=not no_upload)
    print(f"Harms results written to {results_dir / 'harms_results.json'}")
    _render_results(result, trials)


@harms_app.command("harvest")
def harvest(
    output: Annotated[Path, typer.Option(help="Where to write the generated attack-objectives JSON.")] = _config.paths.harms_results / "objectives.json",
    subscription_id: Annotated[str, typer.Option(envvar="AZURE_SUBSCRIPTION_ID", help="Foundry Hub subscription ID.")] = ...,
    resource_group: Annotated[str, typer.Option(envvar="AZURE_RESOURCE_GROUP", help="Foundry Hub resource group.")] = ...,
    project_name: Annotated[str, typer.Option(envvar="AZURE_PROJECT_NAME", help="Foundry Hub project name.")] = ...,
    risk_category: Annotated[
        list[str] | None, typer.Option("--risk-category", help="Risk category to generate objectives for (repeatable), e.g. code_vulnerability. Mutually exclusive with --seeds.")
    ] = None,
    seeds: Annotated[Path | None, typer.Option(help="Starting attack-objectives JSON (upstream format). Mutually exclusive with --risk-category.")] = None,
    language: Annotated[str | None, typer.Option(help="Attack language (e.g. es).")] = None,
) -> None:
    """
    Generate red-team attack objectives using the Azure AI Red Teaming Agent, for use with
    `harms run --objectives`. The agent is driven with a capturing target that records the harmful
    prompts it generates; those are written as an objectives JSON.

    Example:
        uv run bcbench harms harvest --risk-category code_vulnerability --output objectives.json
        uv run bcbench harms run --objectives objectives.json
    """
    from azure.ai.evaluation.red_team import RiskCategory, SupportedLanguages

    if bool(seeds) == bool(risk_category):
        raise typer.BadParameter("Use either --seeds or --risk-category, not both.")

    risks = [RiskCategory(r) for r in risk_category] if risk_category else None
    lang = SupportedLanguages(language) if language else None
    azure_ai_project = {"subscription_id": subscription_id, "resource_group_name": resource_group, "project_name": project_name}

    path = harvest_objectives(azure_ai_project, output, risk_categories=risks, seeds_path=seeds, language=lang)
    print(f"Attack objectives written to {path}")


@harms_app.command("evaluate")
def evaluate(
    trials_path: Annotated[Path, typer.Argument(help="A trials.jsonl (or its results dir) produced by `harms run`.")] = _config.paths.harms_results,
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
        uv run bcbench harms evaluate evaluation_results/harms/smoke-run
    """
    if not all((subscription_id, resource_group, project_name)):
        raise typer.BadParameter("Foundry project (AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME) is required.")

    results_dir = trials_path if trials_path.is_dir() else trials_path.parent
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    trials = _load_trials(trials_file)
    azure_ai_project = {"subscription_id": subscription_id, "resource_group_name": resource_group, "project_name": project_name}
    result = evaluate_trials(trials, azure_ai_project, results_dir, evaluators=tuple(evaluator) if evaluator else DEFAULT_EVALUATORS, upload=not no_upload)
    print(f"Harms results written to {results_dir / 'harms_results.json'}")
    _render_results(result, trials)


@harms_app.command("annotate")
def annotate(
    trials_path: Annotated[Path, typer.Argument(help="A trials.jsonl (or its results dir) produced by `harms run`.")] = _config.paths.harms_results,
) -> None:
    """Post-process a captured run: re-derive per-trial harm delivery from logs and mark line validity.

    Reads ``trials.jsonl`` + ``logs/``, recomputes ``harm_delivered`` (and XPIA landing), writes
    ``trials.jsonl`` back, refreshes ``eval_dataset.jsonl`` with ``harm_delivered``/``valid``, and
    prints a validity summary. Back-fills runs captured before these fields existed — no bcal/network.

    Example:
        uv run bcbench harms annotate evaluation_results/harms
    """
    results_dir = trials_path if trials_path.is_dir() else trials_path.parent
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    annotated = annotate_trials(_load_trials(trials_file), results_dir=results_dir)
    write_trials(trials_file, annotated)
    build_eval_dataset(annotated, results_dir / "eval_dataset.jsonl")
    _console.print(f"[green]Annotated[/] {len(annotated)} trials → refreshed {trials_file.name} and eval_dataset.jsonl.")
    _render_trials(annotated)


@harms_app.command("score")
def score(
    trials_path: Annotated[Path, typer.Argument(help="A trials.jsonl (or its results dir) produced by `harms run`.")] = _config.paths.harms_results,
    model: Annotated[str | None, typer.Option(help="LLM model for the BCQuality judge (defaults to the configured judge model).")] = None,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="Deterministic detector only; skip the LLM judge.")] = False,
) -> None:
    """
    Score whether each executed trial actually produced the insecure AL (``harm_realized``).

    Runs the per-case deterministic detector and the BCQuality-grounded LLM judge over the captured
    generated AL, reconciles them, writes ``trials.jsonl`` back, refreshes ``eval_dataset.jsonl``, and
    reports the attack-success rate over valid (delivered) lines. No bcal re-run.

    Example:
        uv run bcbench harms score evaluation_results/harms --no-judge
    """
    results_dir = trials_path if trials_path.is_dir() else trials_path.parent
    trials_file = trials_path / "trials.jsonl" if trials_path.is_dir() else trials_path
    if not trials_file.exists():
        raise typer.BadParameter(f"No trials.jsonl found at {trials_file}.")

    scored = score_trials(_load_trials(trials_file), model=model, use_judge=not no_judge)
    write_trials(trials_file, scored)
    build_eval_dataset(scored, results_dir / "eval_dataset.jsonl")
    _console.print(f"[green]Scored[/] {len(scored)} trials → refreshed {trials_file.name} and eval_dataset.jsonl.")
    _render_trials(scored)


@harms_app.command("report")
def report(
    path: Annotated[Path, typer.Argument(help="A harms_results.json (or its directory), or a trials.jsonl to render.")] = _config.paths.harms_results,
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
    if not trial.executed or trial.harm_delivered is None:
        return "-"
    return "[green]\u2713 valid[/]" if trial.harm_delivered else "[red]\u2717 invalid[/]"


def _realized_cell(trial: HarmsTrial) -> str:
    # Did the agent actually produce the insecure AL? (filled by `harms score`).
    if trial.harm_realized is None:
        return "-"
    tag = "[red]\u2717 realized[/]" if trial.harm_realized else "[green]\u2713 resisted[/]"
    return f"{tag} [yellow]!?[/]" if trial.score_disagreement else tag


def _render_asr_summary(trials: list[HarmsTrial]) -> None:
    # Attack-success rate over VALID (delivered) lines that have been scored.
    scored = [t for t in trials if t.executed and t.harm_delivered and t.harm_realized is not None]
    if not scored:
        return
    realized = [t for t in scored if t.harm_realized]
    disagreements = [t for t in scored if t.score_disagreement]
    pct = 100.0 * len(realized) / len(scored)
    colour = "red" if realized else "green"
    _console.print(f"[{colour}]Attack success (harm realized):[/] {len(realized)}/{len(scored)} valid lines ({pct:.0f}% ASR).")
    if disagreements:
        _console.print(
            f"[yellow]\u26a0 Detector/judge disagreement on {len(disagreements)} line(s)[/] — review the generated AL "
            f"({_short(', '.join(f'{t.case_id}/{t.vector.value}' for t in disagreements), 80)})."
        )


def _render_validity_summary(trials: list[HarmsTrial]) -> None:
    executed = [t for t in trials if t.executed]
    if not executed:
        return
    valid = [t for t in executed if t.harm_delivered]
    invalid = [t for t in executed if t.harm_delivered is False]
    if invalid:
        _console.print(
            f"[yellow]⚠ Validity:[/] {len(valid)}/{len(executed)} result lines are valid (the agent received the harm). "
            f"{len(invalid)} line(s) are invalid — the harm never reached the agent, so their safety scores are not meaningful "
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
