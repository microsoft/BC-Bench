from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import EvaluationResultSummary, calculate_average_tool_usage

logger = get_logger(__name__)
console = Console()


def _status_style(status_label: str) -> tuple[str, str]:
    """Return (rich_color, github_emoji) for a status label."""
    if status_label in ("Timeout", "Error", "Failed"):
        return "red", ":x:"
    if status_label == "Unscored":
        return "yellow", ":grey_question:"
    return "green", ":white_check_mark:"


def create_console_summary(results: Sequence[BaseEvaluationResult], summary: EvaluationResultSummary) -> None:
    console.print("\n[bold cyan]Evaluation Results Summary[/bold cyan]")
    console.print(f"Total Processed: [bold]{len(results)}[/bold], using [bold]{results[0].agent_name}({results[0].model})[/bold]")
    console.print(f"Category: [bold]{results[0].category.value}[/bold]")
    console.print(f"MCP Servers: [bold]{', '.join(results[0].experiment.mcp_servers) if results[0].experiment and results[0].experiment.mcp_servers else 'None'}[/bold]")
    console.print(f"AL LSP: [bold]{'Yes' if results[0].experiment and results[0].experiment.al_lsp_enabled else 'No'}[/bold]")
    console.print(f"Custom Instructions: [bold]{'Yes' if results[0].experiment and results[0].experiment.custom_instructions else 'No'}[/bold]")
    console.print(f"Skills: [bold]{'Yes' if results[0].experiment and results[0].experiment.skills_enabled else 'No'}[/bold]")
    console.print(f"Custom Agent: [bold]{results[0].experiment.custom_agent if results[0].experiment and results[0].experiment.custom_agent else 'N/A'}[/bold]")

    metrics = summary.render_console_metrics()
    if metrics is not None:
        console.print(metrics)

    # Display average tool usage if available
    tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]
    if tool_usages:
        avg_usage = calculate_average_tool_usage(tool_usages)
        if avg_usage:
            console.print("\n[bold cyan]Average Tool Usage[/bold cyan]")
            sorted_tools = sorted(avg_usage.items(), key=lambda x: x[1], reverse=True)
            for tool_name, count in sorted_tools:
                console.print(f"  {tool_name}: [bold]{count}[/bold]")

    table = Table(title="\nDetailed Results", show_lines=True)
    table.add_column("Instance ID", style="cyan", no_wrap=True)
    table.add_column("Project", style="magenta", no_wrap=True)
    table.add_column("Status", justify="center")

    # Dynamic columns from display_row()
    extra_columns = list(results[0].display_row.keys()) if results else []
    for col_name in extra_columns:
        table.add_column(col_name, style="yellow")

    table.add_column("Error Message", style="dim")

    for result in results:
        color, _ = _status_style(result.status_label)
        status = f"[{color}]{result.status_label}[/{color}]"
        extra_values = list(result.display_row.values())
        table.add_row(result.instance_id, result.project, status, *extra_values, result.error_message or "")

    console.print(table)
    console.print()


def _get_short_error_message(error_message: str | None) -> str:
    """Extract the first line of an error message for summary display."""
    if not error_message:
        return ""
    first_line = error_message.split("\n")[0].rstrip(":")
    return first_line.replace("|", "\\|")


def create_github_job_summary(results: Sequence[BaseEvaluationResult], summary: EvaluationResultSummary) -> None:
    metrics_section: str = summary.render_github_metrics_markdown().strip()

    # Calculate average tool usage
    tool_usage_section: str = ""
    tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]
    if tool_usages:
        avg_usage = calculate_average_tool_usage(tool_usages)
        if avg_usage:
            sorted_tools = sorted(avg_usage.items(), key=lambda x: x[1], reverse=True)
            tool_lines = [f"  - `{tool}`: {count}" for tool, count in sorted_tools]
            tool_usage_section = "## Average Tool Usage\n" + "\n".join(tool_lines)

    header_section: str = "\n".join(
        [
            f"Total entries processed: {len(results)}, using **{results[0].agent_name} ({results[0].model})**",
            f"- Category: `{results[0].category.value}`",
            f"- MCP Servers used: {', '.join(results[0].experiment.mcp_servers) if results[0].experiment and results[0].experiment.mcp_servers else 'None'}",
            f"- AL LSP: {'Yes' if results[0].experiment and results[0].experiment.al_lsp_enabled else 'No'}",
            f"- Custom Instructions: {'Yes' if results[0].experiment and results[0].experiment.custom_instructions else 'No'}",
            f"- Skills: {'Yes' if results[0].experiment and results[0].experiment.skills_enabled else 'No'}",
            f"- Custom Agent: {results[0].experiment.custom_agent if results[0].experiment and results[0].experiment.custom_agent else 'N/A'}",
        ]
    )
    sections: list[str] = [header_section, *(section for section in [metrics_section, tool_usage_section] if section), "## Detailed Results\n\n"]
    markdown_summary: str = "\n\n".join(sections)

    # Dynamic columns from display_row()
    extra_columns = list(results[0].display_row.keys()) if results else []
    extra_headers = " | ".join(extra_columns)
    extra_separator = " | ".join("------" for _ in extra_columns)

    if extra_columns:
        markdown_summary += f"| Instance ID | Project | Status | {extra_headers} | Error Message |\n"
        markdown_summary += f"|-------------|---------|--------|{extra_separator}|---------------|\n"
    else:
        markdown_summary += "| Instance ID | Project | Status | Error Message |\n"
        markdown_summary += "|-------------|---------|--------|---------------|\n"

    for result in results:
        _, status_icon = _status_style(result.status_label)
        status_text = f"{status_icon} {result.status_label}"
        error_msg = _get_short_error_message(result.error_message)
        extra_values = " | ".join(result.display_row.values())
        if extra_columns:
            markdown_summary += f"| `{result.instance_id}` | `{result.project}` | {status_text} | {extra_values} | {error_msg} |\n"
        else:
            markdown_summary += f"| `{result.instance_id}` | `{result.project}` | {status_text} | {error_msg} |\n"

    _write_github_step_summary(markdown_summary)


def _write_github_step_summary(content: str) -> None:
    config = get_config()
    if config.env.github_step_summary:
        with open(config.env.github_step_summary, "a", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        logger.info("Wrote evaluation summary to GitHub Actions step summary")
