"""CLI command for AI red teaming BC-Bench agents (POC)."""

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from azure.ai.evaluation.red_team import AttackStrategy, RiskCategory, SupportedLanguages
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
    # Only the nl2al (BCal) for now. Pluggable so Copilot/Claude could be added later.
    BCAL = "bcal"


@redteam_app.command("scan")
def scan(
    subscription_id: Annotated[str, typer.Option(envvar="AZURE_SUBSCRIPTION_ID", help="Azure subscription ID of the Foundry Hub project for AI Red Teaming Agent.")],
    resource_group: Annotated[str, typer.Option(envvar="AZURE_RESOURCE_GROUP", help="Resource group of the Foundry Hub project for AI Red Teaming Agent.")],
    project_name: Annotated[str, typer.Option(envvar="AZURE_PROJECT_NAME", help="Name of the Foundry Hub project for AI Red Teaming Agent.")],
    language: Annotated[SupportedLanguages, typer.Option(help="Attack language (e.g. es).")],
    seeds: Annotated[Path | None, typer.Option(help="Custom attack seed prompts JSON (upstream format). Mutually exclusive with --risk-category.")] = None,
    risk_category: Annotated[list[RiskCategory] | None, typer.Option("--risk-category", help="Built-in risk category (repeatable), e.g. code_vulnerability. Mutually exclusive with --seeds.")] = None,
    attack_strategy: Annotated[list[AttackStrategy] | None, typer.Option("--attack-strategy", help="Attack strategy (repeatable), e.g. base64, flip, easy.")] = None,
    target: Annotated[RedTeamTarget, typer.Option(help="Agent under test")] = RedTeamTarget.BCAL,
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend used by the bcal target.")] = BCalLLMBackend.AZURE_OPENAI,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (required for azure-openai backend).")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (required for azure-openai backend).")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (external-command backend).")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model/deployment (external-command backend).")] = None,
    output: Annotated[Path, typer.Option(help="Where to write the upstream scorecard JSON.")] = _config.paths.redteam_scorecard,
    scan_name: Annotated[str, typer.Option(help="Scan name shown in the shared Foundry project. Defaults to bcbench-redteam-<timestamp>.")] = f"bcbench-redteam-{datetime.now():%Y%m%d-%H%M%S}",
) -> None:
    """
    Run an AI red teaming Agent scan against a BC-Bench agent.

    Requires a Foundry Hub project via the AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME env vars (plus Azure credentials, e.g. `az login`).
    The bcal symbol cache is auto-populated from the BC artifacts cache (run scripts/Download-BCSymbols.ps1 first).

    Examples:
        uv run bcbench redteam scan --risk-category code_vulnerability
        uv run bcbench redteam scan --seeds dataset/redteam/attack_objectives.json
    """
    from bcbench.redteam import build_bcal_target, run_scan

    if bool(seeds) == bool(risk_category):
        raise typer.BadParameter("Use either --seeds or --risk-category, not both (they are alternative objective sources).")

    output.parent.mkdir(parents=True, exist_ok=True)

    # Only support NL2AL for now, we will think about extensibility later.
    scan_target = build_bcal_target(
        package_cache_path=_config.paths.evaluation_results_path / "redteam" / _config.file_patterns.alpackages_dirname,
        export_base=output.parent / "bcal-exports",
        backend_config=BCalBackendConfig(
            backend=backend,
            endpoint=endpoint,
            deployment=deployment,
            command=llm_command,
            model=llm_model,
        ),
    )

    run_scan(
        target=scan_target,
        azure_ai_project={
            "subscription_id": subscription_id,
            "resource_group_name": resource_group,
            "project_name": project_name,
        },
        output_path=output,
        scan_name=scan_name,
        seeds_path=seeds,
        risk_categories=risk_category,
        attack_strategies=attack_strategy,
        language=language,
    )
    print(f"Red team scorecard written to {output}")
    _render_scorecard(_load_scorecard(output))


@redteam_app.command("report")
def report(
    path: Annotated[Path, typer.Argument(help="Scorecard to render: the scan --output, its directory, or an evaluation_results.json file.")] = _config.paths.redteam_scorecard,
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


def _rows_table(details: list[Json]) -> Table:
    table = Table(title="Attack details", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    for heading in ("#", "Risk", "Technique", "Result", "Attack prompt", "Target response"):
        table.add_column(heading)
    for index, row in enumerate(details, start=1):
        result = "[red]\u2717 broke[/]" if row.get("attack_success") else "[green]\u2713 resisted[/]"
        table.add_row(str(index), str(row.get("risk_category", "-")), str(row.get("attack_technique", "-")), result, _short(_turn(row, "user")), _short(_turn(row, "assistant")))
    return table


def _render_scorecard(data: Json) -> None:
    details: list[Json] = data.get("attack_details", [])

    _console.print()
    if details:
        _console.print(_rows_table(details))
    if url := data.get("studio_url"):
        _console.print(f"Foundry studio: {url}")
