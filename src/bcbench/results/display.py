from rich.console import Console
from rich.table import Table

from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results.evaluation_result import BaseEvaluationResult

logger = get_logger(__name__)
console = Console()


def create_console_summary(results: list[BaseEvaluationResult]) -> None:
    total = len(results)
    resolved = sum(r.resolved for r in results)
    failed = total - resolved

    console.print("\n[bold cyan]Evaluation Results Summary[/bold cyan]")
    console.print(f"Total Processed: [bold]{total}[/bold], using [bold]{results[0].agent_name}({results[0].model})[/bold]")
    console.print(f"Category: [bold]{results[0].category.value}[/bold]")
    console.print(f"Resolved: [bold green]{resolved}[/bold green]")
    console.print(f"Failed: [bold red]{failed}[/bold red]")

    table = Table(title="\nDetailed Results", show_lines=True)
    table.add_column("Instance ID", style="cyan", no_wrap=True)
    table.add_column("Project", style="magenta", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("MCP Servers", style="yellow")
    table.add_column("Custom Instructions", style="yellow")
    table.add_column("Error Message", style="dim")

    for result in results:
        status = "[green]Success[/green]" if result.resolved else "[red]Failed[/red]"
        mcp_servers = ", ".join(result.mcp_servers) if result.mcp_servers else "N/A"
        custom_instructions = "Yes" if result.custom_instructions else "No"
        table.add_row(result.instance_id, result.project, status, mcp_servers, custom_instructions, result.error_message or "")

    console.print(table)
    console.print()


def create_github_job_summary(results: list[BaseEvaluationResult]) -> None:
    total = len(results)
    resolved = sum(r.resolved for r in results)
    failed = total - resolved

    success_icon = ":white_check_mark:" if failed == 0 else ":x:"
    mcp_servers = ", ".join(results[0].mcp_servers) if results[0].mcp_servers else "None"
    custom_instructions = "Yes" if results[0].custom_instructions else "No"
    markdown_summary = f"""Total entries processed: {total}, using **{results[0].agent_name} ({results[0].model})**
- Category: `{results[0].category.value}`
- MCP Servers used: {mcp_servers}
- Custom Instructions: {custom_instructions}
- Successful evaluations: {resolved} :white_check_mark:
- Failed evaluations: {failed} {success_icon}

## Detailed Results

| Instance ID | Project | Status | Error Message |
|-------------|---------|--------|---------------|
"""
    for result in results:
        status_icon = ":white_check_mark:" if result.resolved else ":x:"
        status_text = f"{status_icon} {'Success' if result.resolved else 'Failed'}"
        error_msg = result.error_message or ""
        error_msg = error_msg.replace("|", "\\|")
        markdown_summary += f"| `{result.instance_id}` | `{result.project}` | {status_text} | {error_msg} |\n"

    _write_github_step_summary(markdown_summary)


def _write_github_step_summary(content: str) -> None:
    config = get_config()
    if config.env.github_step_summary:
        with open(config.env.github_step_summary, "a", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        logger.info("Wrote evaluation summary to GitHub Actions step summary")
