"""CLI command for AI red teaming BC-Bench agents (POC)."""

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.types import BCalLLMBackend

# Loose JSON alias (aliasing keeps `Any` out of function signatures, satisfying ANN401).
type Json = dict[str, Any]

logger = get_logger(__name__)
_config = get_config()
_console = Console()

redteam_app = typer.Typer(help="Red team BC-Bench agents using azure-ai-evaluation[redteam]")


class RedTeamTarget(StrEnum):
    # POC: only the nl2al agent (BCal). Pluggable so Copilot/Claude can be added later.
    BCAL = "bcal"


# Red-team objectives live in their own folder, separate from the accuracy datasets.
_DEFAULT_SEEDS = _config.paths.dataset_dir / "redteam" / "attack_objectives.json"
_DEFAULT_OUTPUT = _config.paths.evaluation_results_path / "redteam" / "scorecard.json"
# bcal reads BC symbols from here; auto-populated from the artifacts cache if missing.
_DEFAULT_PACKAGE_CACHE = _config.paths.evaluation_results_path / "redteam" / ".alpackages"


@redteam_app.command("scan")
def scan(
    # Foundry Hub project is identified by these three values (dict form upstream).
    subscription_id: Annotated[str, typer.Option(envvar="AZURE_SUBSCRIPTION_ID", help="Azure subscription ID of the Foundry Hub project.")],
    resource_group: Annotated[str, typer.Option(envvar="AZURE_RESOURCE_GROUP", help="Resource group of the Foundry Hub project.")],
    project_name: Annotated[str, typer.Option(envvar="AZURE_PROJECT_NAME", help="Name of the Foundry Hub project.")],
    target: Annotated[RedTeamTarget, typer.Option(help="Agent under test")] = RedTeamTarget.BCAL,
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend used by the bcal target.")] = BCalLLMBackend.AZURE_OPENAI,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (azure-openai backend).")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (azure-openai backend).")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (external-command backend).")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model/deployment (external-command backend).")] = None,
    seeds: Annotated[Path | None, typer.Option(help="Custom attack seed prompts JSON (upstream format). Mutually exclusive with --risk-category.")] = None,
    risk_category: Annotated[list[str] | None, typer.Option("--risk-category", help="Built-in risk category (repeatable), e.g. CodeVulnerability, Violence. Mutually exclusive with --seeds.")] = None,
    attack_strategy: Annotated[list[str] | None, typer.Option("--attack-strategy", help="Attack strategy (repeatable), e.g. Base64, Flip, EASY.")] = None,
    language: Annotated[str | None, typer.Option(help="Attack language (e.g. Spanish); defaults to English.")] = None,
    package_cache_path: Annotated[
        Path, typer.Option(help=".alpackages symbol cache for bcal. Auto-populated from the BC artifacts cache if missing (run scripts/Download-BCSymbols.ps1 first).")
    ] = _DEFAULT_PACKAGE_CACHE,
    output: Annotated[Path, typer.Option(help="Where to write the upstream scorecard JSON.")] = _DEFAULT_OUTPUT,
    scan_name: Annotated[str | None, typer.Option(help="Scan name shown in the shared Foundry project. Defaults to bcbench-redteam-<timestamp>.")] = None,
) -> None:
    """
    Run an AI red teaming scan against a BC-Bench agent.

    Requires the optional dependency group (`uv sync --group redteam`) and a Foundry Hub
    project via the AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME env
    vars (plus Azure credentials, e.g. `az login`).

    When neither --seeds nor --risk-category is given, the separate red-team seed
    dataset (dataset/redteam/attack_objectives.json) is used.

    Examples:
        uv run bcbench redteam scan --risk-category CodeVulnerability
        uv run bcbench redteam scan --seeds dataset/redteam/attack_objectives.json
    """
    # Lazy import: only pull azure-ai-evaluation when a scan actually runs.
    from bcbench.redteam import build_bcal_target, run_scan

    if seeds is not None and risk_category:
        raise typer.BadParameter("Use either --seeds or --risk-category, not both (they are alternative objective sources).")

    # Default to the separate red-team seed dataset when no source is specified.
    seeds_path = seeds if seeds is not None else (None if risk_category else _DEFAULT_SEEDS)

    output.parent.mkdir(parents=True, exist_ok=True)

    if target is RedTeamTarget.BCAL:
        scan_target = build_bcal_target(
            package_cache_path=package_cache_path,
            export_base=output.parent / "bcal-exports",
            backend_config=BCalBackendConfig(
                backend=backend,
                endpoint=endpoint,
                deployment=deployment,
                command=llm_command,
                model=llm_model,
            ),
        )
    else:  # pragma: no cover - single-target POC guard
        raise typer.BadParameter(f"Unsupported target: {target}")

    # Brand the scan so BC-Bench runs are easy to spot in the shared Foundry project.
    effective_scan_name = scan_name or f"bcbench-redteam-{datetime.now():%Y%m%d-%H%M%S}"

    run_scan(
        target=scan_target,
        azure_ai_project={
            "subscription_id": subscription_id,
            "resource_group_name": resource_group,
            "project_name": project_name,
        },
        output_path=output,
        scan_name=effective_scan_name,
        seeds_path=seeds_path,
        risk_categories=risk_category,
        attack_strategies=attack_strategy,
        language=language,
    )
    print(f"Red team scorecard written to {output}")
    _render_scorecard(_load_scorecard(output))


@redteam_app.command("report")
def report(
    path: Annotated[Path, typer.Argument(help="Scorecard to render: the scan --output, its directory, or an evaluation_results.json file.")] = _DEFAULT_OUTPUT,
) -> None:
    """
    Render a saved red team scorecard as tables in the terminal.

    Example:
        uv run bcbench redteam report evaluation_results/redteam/scorecard.json
    """
    _render_scorecard(_load_scorecard(path))


# --- Scorecard rendering -----------------------------------------------------
# ASR = Attack Success Rate: the % of attacks that elicited harmful output.
# Unlike accuracy categories, LOWER is better (0 = the agent resisted every attack).

_BCAL_ERROR_MARKERS = ("returned non-zero exit status", "Something went wrong", "bcal produced no output", "bcal timed out")


def _load_scorecard(path: Path) -> Json:
    # The SDK writes a *directory* containing evaluation_results.json; accept that
    # directory, the inner file, or a direct JSON file.
    if path.is_dir():
        path = path / "evaluation_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _turn(row: Json, role: str) -> str:
    # First user turn = the attack; last assistant turn = the target's reply.
    texts = [str(t.get("content", "")) for t in row.get("conversation", []) if t.get("role") == role]
    return (texts[0] if role == "user" else texts[-1]) if texts else ""


def _short(text: str, limit: int = 55) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "\u2026"


def _summary_table(title: str, summary: Json) -> Table:
    # Keys follow the "<name>_asr / _total / _successful_attacks" convention; "overall" first.
    table = Table(title=title, box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    table.add_column("Category / Technique")
    for heading in ("Attacks", "Succeeded", "ASR %"):
        table.add_column(heading, justify="right")
    for name in sorted((k[:-4] for k in summary if k.endswith("_asr")), key=lambda n: (n != "overall", n)):
        asr = float(summary.get(f"{name}_asr", 0.0))
        color = "green" if asr <= 0 else "yellow" if asr < 50 else "red"
        table.add_row(name, str(summary.get(f"{name}_total", "-")), str(summary.get(f"{name}_successful_attacks", "-")), f"[{color}]{asr:.1f}[/]")
    return table


def _rows_table(details: list[Json]) -> Table:
    table = Table(title="Attack details", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    for heading in ("#", "Risk", "Technique", "Result", "Attack prompt", "Target response"):
        table.add_column(heading)
    for index, row in enumerate(details, start=1):
        result = "[red]\u2717 broke[/]" if row.get("attack_success") else "[green]\u2713 resisted[/]"
        table.add_row(str(index), str(row.get("risk_category", "-")), str(row.get("attack_technique", "-")), result, _short(_turn(row, "user")), _short(_turn(row, "assistant")))
    return table


def _render_scorecard(data: Json) -> None:
    scorecard = data.get("scorecard", {})
    details: list[Json] = data.get("attack_details", [])

    _console.print()
    for summary in scorecard.get("risk_category_summary", []):
        _console.print(_summary_table("Risk category summary (ASR \u2014 lower is better)", summary))
    for summary in scorecard.get("attack_technique_summary", []):
        _console.print(_summary_table("Attack technique summary", summary))
    if details:
        _console.print(_rows_table(details))

    errors = sum(any(m in _turn(row, "assistant") for m in _BCAL_ERROR_MARKERS) for row in details)
    if errors:
        _console.print(f"[yellow]Note:[/] {errors}/{len(details)} responses look like BCal errors, so the judge scored error text, not generated AL.")
    if url := data.get("studio_url"):
        _console.print(f"Foundry studio: {url}")
