import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from bcbench.config import get_config
from bcbench.logger import get_logger

logger = get_logger(__name__)
console = Console()


@dataclass(slots=True)
class EvaluationResult:
    instance_id: str
    version: str
    model: str
    agent_name: str

    # Accuracy / Quality metrics
    resolved: bool
    build: bool  # Whether the final code built successfully

    # Error tracking
    error_message: str | None = None

    # Performance and Reliability metrics
    agent_execution_time: float | None = None  # Time spent running the agent

    # Token consumption
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def save(self, output_dir: Path, result_file: str = "instance_results.jsonl") -> None:
        output_file = output_dir / result_file
        with open(output_file, "a") as f:
            result_dict = {
                "instance_id": self.instance_id,
                "resolved": self.resolved,
                "model": self.model,
                "agent_name": self.agent_name,
                "build": self.build,
                "error_message": self.error_message,
                "environment_setup_version": self.version,
                "agent_execution_time": self.agent_execution_time,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
            }
            f.write(json.dumps(result_dict) + "\n")

        logger.info(f"Saved evaluation result for {self.instance_id} to {output_file}")


@dataclass(slots=True)
class EvaluationResultSummary:
    total: int
    resolved: int
    failed: int
    build: int

    date: date

    model: str
    agent_name: str

    average_duration: float
    average_prompt_tokens: float
    average_completion_tokens: float

    github_run_id: str | None = None

    def save(self, output_dir: Path, summary_file: str = "evaluation_summary.json") -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            summary_dict = {
                "total": self.total,
                "resolved": self.resolved,
                "failed": self.failed,
                "build": self.build,
                "date": self.date.isoformat(),
                "model": self.model,
                "agent_name": self.agent_name,
                "average_duration": self.average_duration,
                "average_prompt_tokens": self.average_prompt_tokens,
                "average_completion_tokens": self.average_completion_tokens,
                "github_run_id": self.github_run_id,
            }
            f.write(json.dumps(summary_dict, indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")


def summarize_results(results_dir: Path, result_pattern: str, run_id: str) -> None:
    """Read evaluation results from file(s) and print a summary using rich tables.

    This function will search for all files matching result_file pattern in results_dir
    and its subdirectories, aggregating results from all found files.
    """
    results: list[EvaluationResult] = []

    # Find all matching result files in the directory and subdirectories
    result_files = list(results_dir.rglob(result_pattern))

    if not result_files:
        logger.error(f"No results files matching '{result_pattern}' found in {results_dir}")
        raise RuntimeError(f"No results files matching '{result_pattern}' found in {results_dir}")

    logger.info(f"Found {len(result_files)} result file(s) to process")

    for results_path in result_files:
        logger.info(f"Reading results from: {results_path}")
        with open(results_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # Map environment_setup_version back to version
                    result = EvaluationResult(
                        instance_id=data.get("instance_id"),
                        version=data.get("environment_setup_version"),
                        model=data.get("model"),
                        agent_name=data.get("agent_name"),
                        resolved=data.get("resolved"),
                        build=data.get("build"),
                        error_message=data.get("error_message"),
                        agent_execution_time=data.get("agent_execution_time"),
                        prompt_tokens=data.get("prompt_tokens"),
                        completion_tokens=data.get("completion_tokens"),
                    )
                    results.append(result)

    if not results:
        logger.error("No results found in the result files")
        raise RuntimeError("No results found in the result files")

    total = len(results)
    resolved = sum(1 for r in results if r.resolved)
    failed = total - resolved
    build_count = sum(1 for r in results if r.build)

    # Calculate averages (handling None values)
    durations = [r.agent_execution_time for r in results if r.agent_execution_time is not None]
    prompt_tokens_list = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
    completion_tokens_list = [r.completion_tokens for r in results if r.completion_tokens is not None]

    average_duration = sum(durations) / len(durations) if durations else 0.0
    average_prompt_tokens = sum(prompt_tokens_list) / len(prompt_tokens_list) if prompt_tokens_list else 0.0
    average_completion_tokens = sum(completion_tokens_list) / len(completion_tokens_list) if completion_tokens_list else 0.0

    summary = EvaluationResultSummary(
        total=total,
        resolved=resolved,
        failed=failed,
        build=build_count,
        date=date.today(),
        model=results[0].model,
        agent_name=results[0].agent_name,
        average_duration=average_duration,
        average_prompt_tokens=average_prompt_tokens,
        average_completion_tokens=average_completion_tokens,
        github_run_id=run_id,
    )
    summary.save(results_dir)

    config = get_config()
    if config.env.github_actions:
        _create_github_job_summary(results, total, resolved, failed)
    else:
        _create_console_summary(results, total, resolved, failed)


def _create_console_summary(results: list[EvaluationResult], total: int, resolved: int, failed: int) -> None:
    console.print("\n[bold cyan]Evaluation Results Summary[/bold cyan]")
    console.print(f"Total Processed: [bold]{total}[/bold], using [bold]{results[0].agent_name}({results[0].model})[/bold]")
    console.print(f"Resolved: [bold green]{resolved}[/bold green]")
    console.print(f"Failed: [bold red]{failed}[/bold red]")

    # Create results table
    table = Table(title="\nDetailed Results", show_lines=True)
    table.add_column("Instance ID", style="cyan", no_wrap=True)
    table.add_column("Version", style="magenta", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Error Message", style="dim")

    for result in results:
        status = "[green]Success[/green]" if result.resolved else "[red]Failed[/red]"
        table.add_row(result.instance_id, result.version, status, result.error_message or "")

    console.print(table)
    console.print()


def _create_github_job_summary(results: list[EvaluationResult], total: int, resolved: int, failed: int) -> None:
    success_icon = ":white_check_mark:" if failed == 0 else ":x:"
    markdown_summary = f"""Total entries processed: {total}, using **{results[0].agent_name}({results[0].model})**
- Successful evaluations: {resolved} :white_check_mark:
- Failed evaluations: {failed} {success_icon}

## Detailed Results

| Instance ID | Version | Status | Error Message |
|-------------|---------|--------|---------------|
"""
    for result in results:
        status_icon = ":white_check_mark:" if result.resolved else ":x:"
        status_text = f"{status_icon} {'Success' if result.resolved else 'Failed'}"
        error_msg = result.error_message or ""
        # Escape pipe characters in error messages to prevent table breaking
        error_msg = error_msg.replace("|", "\\|")
        markdown_summary += f"| `{result.instance_id}` | `{result.version}` | {status_text} | {error_msg} |\n"

    _write_github_step_summary(markdown_summary)


def _write_github_step_summary(content: str) -> None:
    """Write content to GitHub Actions step summary."""
    config = get_config()
    if config.env.github_step_summary:
        with open(config.env.github_step_summary, "a", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        logger.info("Wrote evaluation summary to GitHub Actions step summary")
