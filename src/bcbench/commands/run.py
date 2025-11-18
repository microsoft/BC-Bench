"""CLI commands for running agents."""

from pathlib import Path
from typing import Literal

import typer
from typing_extensions import Annotated

from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.mini import run_mini_agent
from bcbench.cli_options import (
    ContainerName,
    ContainerPassword,
    ContainerUsername,
    CopilotModel,
    DatasetPath,
    OutputDir,
    RepoPath,
)
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, load_dataset_entries
from bcbench.logger import get_logger
from bcbench.operations import checkout_commit, clean_repo

logger = get_logger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("mini")
def run_mini(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    container_name: ContainerName,
    username: ContainerUsername,
    password: ContainerPassword,
    model: Annotated[Literal["azure/gpt-4.1"], typer.Option(help="Azure AI Foundry Model to use for mini-bc-agent")] = "azure/gpt-4.1",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.nav_repo_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
):
    """
    Run mini-bc-agent on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run mini microsoftInternal__NAV-211710 --step-limit 5
    """
    entry: DatasetEntry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)

    run_mini_agent(
        entry=entry,
        repo_path=repo_path,
        model=model,
        container_name=container_name,
        username=username,
        password=password,
        output_dir=output_dir,
    )


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "claude-haiku-4.5",
    dataset_path: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.nav_repo_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
):
    """
    Run GitHub Copilot CLI on a single entry to generate a patch (without building/testing).

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoftInternal__NAV-211710
    """
    entry: DatasetEntry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)

    run_copilot_agent(entry=entry, repo_path=repo_path, model=model, output_dir=output_dir)


@run_app.command("pr-review")
def run_pr_review(
    entry_index: Annotated[int, typer.Option(help="PR entry index to review (0-based)")] = 0,
    output_file: Annotated[Path | None, typer.Option(help="Save prompt to file")] = None,
    run_agent: Annotated[bool, typer.Option(help="Run Copilot CLI agent to generate comments")] = False,
    model: CopilotModel = "claude-haiku-4.5",
    show_prompt: Annotated[bool, typer.Option(help="Display the prompt before running")] = False,
):
    """
    Run PR security review with Copilot CLI on a single PR entry.

    This loads a PR from prdataset.jsonl, builds the security review prompt with
    instructions and PR data, and optionally runs Copilot CLI to generate comments.

    Example:
        uv run bcbench run pr-review --entry-index 0 --run-agent
        uv run bcbench run pr-review --entry-index 0 --run-agent --show-prompt
        uv run bcbench run pr-review --entry-index 0 --output-file prompt.txt
    """
    import shutil
    import subprocess

    from bcbench.agent.pr_security_review_helper import build_pr_security_review_prompt, load_pr_dataset

    try:
        # Load PR dataset
        logger.info("Loading PR dataset...")
        pr_entries = load_pr_dataset()

        if not pr_entries:
            logger.error("No PR entries found in dataset!")
            raise typer.Exit(1)

        if entry_index >= len(pr_entries):
            logger.error(f"Entry index {entry_index} out of range. Available entries: {len(pr_entries)}")
            raise typer.Exit(1)

        # Get entry
        pr_entry = pr_entries[entry_index]
        logger.info(f"Selected PR: {pr_entry.name}")

        # Build complete prompt
        logger.info("Building security review prompt...")
        prompt = build_pr_security_review_prompt(pr_entry)

        # Save to file if requested
        if output_file:
            output_file_path = Path(output_file)
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            with output_file_path.open("w") as f:
                f.write(prompt)
            logger.info(f"Prompt saved to: {output_file_path}")

        # Display the prompt if requested
        if show_prompt:
            print("\n" + "=" * 80)
            print(f"SECURITY REVIEW PROMPT - {pr_entry.name}")
            print("=" * 80)
            print(prompt)
            print("=" * 80)

            # Display target comments
            if pr_entry.target_comments:
                print("\n" + "=" * 80)
                print("TARGET COMMENTS (Expected AI Output)")
                print("=" * 80)
                for i, target in enumerate(pr_entry.target_comments, 1):
                    print(f"{i}. Line {target['line']}: {target['comment']}")
                print("=" * 80 + "\n")
                logger.info(f"Total target comments expected: {len(pr_entry.target_comments)}")

        # Run agent if requested
        if run_agent:
            logger.info("Running Copilot CLI agent...")
            copilot_cmd = shutil.which("copilot")
            if not copilot_cmd:
                logger.error("Copilot CLI not found. Install with: npm install -g @github/copilot")
                raise typer.Exit(1)

            try:
                print("\n" + "=" * 80)
                print("COPILOT CLI OUTPUT")
                print("=" * 80 + "\n")

                # Create output directory for logs
                output_dir = _config.paths.evaluation_results_path / "pr_review"
                output_dir.mkdir(parents=True, exist_ok=True)

                # Write prompt to a temp file instead of passing via command line
                # (avoids "command line too long" error for large prompts)
                prompt_file = output_dir / f"prompt_{entry_index}.txt"
                with prompt_file.open("w") as f:
                    f.write(prompt)
                logger.debug(f"Prompt written to: {prompt_file}")

                cmd_args = [
                    copilot_cmd,
                    "--allow-all-tools",
                    "--allow-all-paths",
                    f"--model={model}",
                    "--log-level=debug",
                    f"--log-dir={output_dir.resolve()}",
                ]

                # Use stdin instead of command line argument
                logger.debug(f"Running Copilot with model {model}...")
                logger.debug(f"Output directory: {output_dir}")

                # Run subprocess and pipe prompt via stdin
                result = subprocess.run(
                    cmd_args,
                    input=prompt,  # Pass prompt via stdin
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=_config.timeout.github_copilot_cli,
                    text=True,
                    check=False,
                )

                # Print all output
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(result.stderr)

                if result.returncode == 0:
                    logger.info("Copilot CLI completed successfully")
                    print("\n✓ Agent execution completed")
                else:
                    logger.warning(f"Copilot CLI exited with code {result.returncode}")
                    print(f"\n⚠ Agent exited with code {result.returncode}")

                print("\n" + "=" * 80)
                logger.info(f"Copilot logs saved to: {output_dir}")
                print(f"Logs saved to: {output_dir}\n")

            except subprocess.TimeoutExpired:
                logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")
                print(f"\n✗ Timeout: Agent took too long ({_config.timeout.github_copilot_cli}s)")
                raise typer.Exit(1)
            except Exception as e:
                logger.exception(f"Error running Copilot CLI: {e}")
                print(f"\n✗ Error: {e}")
                raise typer.Exit(1)
        elif not show_prompt and not output_file:
            logger.info("Use --run-agent to execute Copilot CLI and generate comments")
            print("\nTip: Run with --run-agent flag to execute Copilot CLI:")
            print(f"  uv run bcbench run pr-review --entry-index {entry_index} --run-agent")

    except Exception as e:
        logger.exception(f"Error: {e}")
        raise typer.Exit(1)


@run_app.command("mini-inspector")
def run_mini_inspector(
    path: Annotated[Path, typer.Argument(help="Directory to search for trajectory files or specific trajectory file")],
    pattern: Annotated[str, typer.Option(help="File pattern to match trajectory files")] = f"*{_config.file_patterns.trajectory_pattern}",
):
    """
    Inspect trajectory files in the given directory or a specific trajectory file.

    Example:
        uv run bcbench run mini-inspector ./outputs/mini_agent_runs/
    """
    from minisweagent.run.inspector import TrajectoryInspector

    if path.is_file():
        trajectory_files = [path]
    elif path.is_dir():
        trajectory_files = sorted(path.rglob(pattern))
        if not trajectory_files:
            raise typer.BadParameter(f"No trajectory files found in '{path}'")
    else:
        raise typer.BadParameter(f"Error: Path '{path}' does not exist")

    inspector = TrajectoryInspector(trajectory_files)
    inspector.run()
