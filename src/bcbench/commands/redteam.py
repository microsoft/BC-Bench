"""CLI command for AI red teaming BC-Bench agents (POC)."""

import json
from datetime import UTC, datetime
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
    backend: Annotated[BCalLLMBackend, typer.Option(envvar="BCAL_LLM_BACKEND", help="BCal LLM backend used by the bcal target.")] = BCalLLMBackend.EXTERNAL_COMMAND,
    endpoint: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_ENDPOINT", help="Azure OpenAI endpoint (required for azure-openai backend).")] = None,
    deployment: Annotated[str | None, typer.Option(envvar="AZURE_OPENAI_DEPLOYMENT", help="Azure OpenAI deployment (required for azure-openai backend).")] = None,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="LLM command (external-command backend).")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="LLM model/deployment (external-command backend).")] = None,
    output: Annotated[Path, typer.Option(help="Where the SDK writes the scan output. It creates a *directory* at this path holding evaluation_results.json.")] = _config.paths.redteam_scorecard,
    scan_name: Annotated[str | None, typer.Option(help="Scan name shown in the shared Foundry project. Defaults to bcbench-redteam-<timestamp>.")] = None,
) -> None:
    """
    Run an AI red teaming Agent scan against a BC-Bench agent.

    Requires the optional redteam dependency group (`uv sync --group redteam`) and a Foundry Hub project via the AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP / AZURE_PROJECT_NAME env vars (plus Azure credentials, e.g. `az login`).
    The bcal symbol cache is auto-populated from the BC artifacts cache (run scripts/Download-BCSymbols.ps1 first).

    Examples:
        uv run bcbench redteam scan --language en --risk-category code_vulnerability
        uv run bcbench redteam scan --language es --seeds dataset/redteam/attack_objectives.json --attack-strategy base64
    """
    from bcbench.redteam import build_bcal_target, run_scan

    # Upstream treats seeds and risk categories as alternative objective sources, so exactly one is required.
    if bool(seeds) == bool(risk_category):
        raise typer.BadParameter("Pass exactly one of --seeds or --risk-category (they are alternative attack-objective sources).")

    scan_name = scan_name or f"bcbench-redteam-{datetime.now(UTC):%Y%m%d-%H%M%S}"
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
    _console.print(f"Red team scan output written to {output}")
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


def _attack_result(attack_success: object) -> str:
    if attack_success is True:
        return "[red]\u2717 broke[/]"
    if attack_success is False:
        return "[green]\u2713 resisted[/]"
    return "[yellow]? unevaluated[/]"


def _rows_table(details: list[Json]) -> Table:
    table = Table(title="Attack details", box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    for heading in ("#", "Risk", "Technique", "Result", "Attack prompt", "Target response"):
        table.add_column(heading)
    for index, row in enumerate(details, start=1):
        result = _attack_result(row.get("attack_success"))
        table.add_row(str(index), str(row.get("risk_category", "-")), str(row.get("attack_technique", "-")), result, _short(_turn(row, "user")), _short(_turn(row, "assistant")))
    return table


def _asr_table(title: str, summary: list[Json]) -> Table | None:
    """Render one of the SDK's ASR summaries.

    The SDK emits a single-row list with the grouping folded into the key names --
    `<group>_asr` / `<group>_total` / `<group>_successful_attacks`, e.g. `code_vulnerability_asr`
    or `baseline_asr`, plus an `overall_*` triple -- so the groups are recovered from the keys.
    """
    if not summary:
        return None
    row = summary[0]
    groups = [key.removesuffix("_asr") for key in row if key.endswith("_asr") and key != "overall_asr"]
    if not groups:
        return None

    table = Table(title=title, box=box.SIMPLE_HEAVY, title_justify="left", title_style="bold")
    for heading in ("Group", "ASR", "Successful", "Total"):
        table.add_column(heading)
    for group in [*groups, "overall"]:
        asr = row.get(f"{group}_asr")
        colour = "green" if asr == 0 else "red"
        table.add_row(group, f"[{colour}]{asr}%[/]", str(row.get(f"{group}_successful_attacks", "-")), str(row.get(f"{group}_total", "-")))
    return table


def _render_scorecard(data: Json) -> None:
    scorecard: Json = data.get("scorecard", {})
    details: list[Json] = data.get("attack_details", [])

    _console.print()
    for title, key in (("Attack success rate by risk category", "risk_category_summary"), ("Attack success rate by technique", "attack_technique_summary")):
        if table := _asr_table(title, scorecard.get(key, [])):
            _console.print(table)
    if details:
        _console.print(_rows_table(details))
    if url := data.get("studio_url"):
        _console.print(f"Foundry studio: {url}")
