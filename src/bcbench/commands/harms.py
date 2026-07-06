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
from bcbench.harms import HarmsTrial, ManualHarmsSource, evaluate_trials, run_harms_suite
from bcbench.harms.case import HarmsVector
from bcbench.harms.evaluate import DEFAULT_EVALUATORS
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
) -> None:
    """
    Run a harms suite against BCAL: expand each vector-invariant case across the vector matrix, run
    bcal per trial, score with Azure AI safety evaluators, and upload results to Foundry.

    Rapid validation: `--dry-run` (no bcal/network), `--limit 1 --vector direct` (one bcal run).

    Examples:
        uv run bcbench harms run --dry-run
        uv run bcbench harms run --limit 1 --vector direct
        uv run bcbench harms run --suite dataset/harms/sample.harms.yaml
    """
    if not dry_run and not all((subscription_id, resource_group, project_name)):
        raise typer.BadParameter("Foundry project (AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME) is required unless --dry-run.")

    results_dir.mkdir(parents=True, exist_ok=True)
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
    for heading in ("#", "Case", "Vector", "Channel", "Injected?", "Tools", "Attack"):
        table.add_column(heading)
    for index, trial in enumerate(trials, start=1):
        channel = "[magenta]XPIA[/]" if trial.channel.value == "indirect" else "[cyan]UPIA[/]"
        table.add_row(str(index), trial.case_id, trial.vector.value, channel, _landed_cell(trial), _short(", ".join(trial.tools_invoked) or "-", 28), _short(trial.attack))
    _console.print()
    _console.print(table)
    _render_injection_summary(trials)


def _landed_cell(trial: HarmsTrial) -> str:
    # Direct trials have no seam injection; the payload is the prompt itself.
    if trial.channel.value != "indirect":
        return "[dim]n/a[/]"
    if trial.injection_landed is None:
        return "-"
    return "[green]\u2713 landed[/]" if trial.injection_landed else "[red]\u2717 missed[/]"


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
        for heading in ("Case", "Vector", "Channel", *_score_columns(rows)):
            rtable.add_column(heading)
        for row in rows:
            scores = [f"{row.get(col, '-')}" for col in _score_columns(rows)]
            rtable.add_row(str(row.get("inputs.case_id", "-")), str(row.get("inputs.vector", "-")), str(row.get("inputs.channel", "-")), *scores)
        _console.print()
        _console.print(rtable)
        _render_injection_summary(trials)
    elif not metrics:
        _render_trials(trials)

    if url := result.get("studio_url"):
        _console.print(f"Foundry studio: {url}")


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
