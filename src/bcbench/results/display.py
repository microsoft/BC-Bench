from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import EvaluationResultSummary, calculate_average_tool_usage

logger = get_logger(__name__)
console = Console()


def create_console_summary(results: Sequence[BaseEvaluationResult], summary: EvaluationResultSummary) -> None:
    total = len(results)
    display_metrics: dict[str, int | float | bool] = summary.display_summary()

    console.print("\n[bold cyan]Evaluation Results Summary[/bold cyan]")
    console.print(f"Total Processed: [bold]{total}[/bold], using [bold]{results[0].agent_name}({results[0].model})[/bold]")
    console.print(f"Category: [bold]{results[0].category.value}[/bold]")
    for key, value in display_metrics.items():
        console.print(f"{key.replace('_', ' ').title()}: [bold]{value}[/bold]")

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

    table.add_column("MCP Servers", style="yellow")
    table.add_column("Custom Instructions", style="yellow")
    table.add_column("Skills", style="yellow")
    table.add_column("Custom Agent", style="yellow")
    table.add_column("Error Message", style="dim")

    for result in results:
        has_error = result.error_message is not None or result.timeout
        status = f"[red]{result.status_label}[/red]" if has_error else f"[green]{result.status_label}[/green]"
        mcp_servers = ", ".join(result.experiment.mcp_servers) if result.experiment and result.experiment.mcp_servers else "N/A"
        custom_instructions = "Yes" if result.experiment and result.experiment.custom_instructions else "No"
        skills = "Yes" if result.experiment and result.experiment.skills_enabled else "No"
        custom_agent = result.experiment.custom_agent if result.experiment and result.experiment.custom_agent else "N/A"
        extra_values = list(result.display_row.values())
        table.add_row(result.instance_id, result.project, status, *extra_values, mcp_servers, custom_instructions, skills, custom_agent, result.error_message or "")

    console.print(table)
    console.print()


def _get_short_error_message(error_message: str | None) -> str:
    """Extract the first line of an error message for summary display."""
    if not error_message:
        return ""
    first_line = error_message.split("\n")[0].rstrip(":")
    return first_line.replace("|", "\\|")


def create_github_job_summary(results: Sequence[BaseEvaluationResult], summary: EvaluationResultSummary) -> None:
    total = len(results)
    display_metrics: dict[str, int | float | bool] = summary.display_summary()
    errors = sum(1 for r in results if r.error_message or r.timeout)

    success_icon = ":white_check_mark:" if errors == 0 else ":x:"

    mcp_servers = ", ".join(results[0].experiment.mcp_servers) if results[0].experiment and results[0].experiment.mcp_servers else "None"
    custom_instructions = "Yes" if results[0].experiment and results[0].experiment.custom_instructions else "No"
    skills = "Yes" if results[0].experiment and results[0].experiment.skills_enabled else "No"
    custom_agent = results[0].experiment.custom_agent if results[0].experiment and results[0].experiment.custom_agent else "N/A"

    # Calculate average tool usage
    tool_usage_section = ""
    tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]
    if tool_usages:
        avg_usage = calculate_average_tool_usage(tool_usages)
        if avg_usage:
            sorted_tools = sorted(avg_usage.items(), key=lambda x: x[1], reverse=True)
            tool_lines = [f"  - `{tool}`: {count}" for tool, count in sorted_tools]
            tool_usage_section = "\n\n## Average Tool Usage\n" + "\n".join(tool_lines)

    # Build category-specific summary lines
    display_lines = "\n".join(f"- {key.replace('_', ' ').title()}: {value}" for key, value in display_metrics.items())

    markdown_summary = f"""Total entries processed: {total}, using **{results[0].agent_name} ({results[0].model})**
- Category: `{results[0].category.value}`
- MCP Servers used: {mcp_servers}
- Custom Instructions: {custom_instructions}
- Skills: {skills}
- Custom Agent: {custom_agent}
{display_lines}
- Errors: {errors} {success_icon}{tool_usage_section}

## Detailed Results

"""

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
        has_error = result.error_message is not None or result.timeout
        status_icon = ":x:" if has_error else ":white_check_mark:"
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
