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

@run_app.command("pr-review-evals")
def run_pr_review_evals(
    output_file: Annotated[Path | None, typer.Option(help="Save results to file")] = None,
    model: CopilotModel = "claude-haiku-4.5",
    show_prompts: Annotated[bool, typer.Option(help="Display prompts and outputs")] = False,
):
    """
    Run PR security review evaluation on all PR entries in the dataset.

    This will:
    1. Load all PR entries from prdataset.jsonl
    2. Run Copilot CLI on each entry
    3. Use Copilot CLI as LLM judge to evaluate if actual comments cover expected concerns
    4. Write results to a file

    Example:
        uv run bcbench run pr-review-evals
        uv run bcbench run pr-review-evals --output-file results.jsonl
        uv run bcbench run pr-review-evals --show-prompts
    """
    import json
    import shutil
    import subprocess
    from dataclasses import asdict, dataclass

    from bcbench.agent.pr_security_review_helper import build_pr_security_review_prompt, load_pr_dataset

    @dataclass
    class PRReviewResult:
        pr_name: str
        pr_description: str
        output: str
        expected_output: list[dict[str, str | int]]
        passed: bool
        judge_reason: str | None = None
        error_message: str | None = None

    try:
        # Check if Copilot CLI is available
        copilot_cmd = shutil.which("copilot")
        if not copilot_cmd:
            logger.error("Copilot CLI not found. Install with: npm install -g @github/copilot")
            raise typer.Exit(1)

        # Load judge prompt template
        judge_prompt_path = _config.paths.bc_bench_root / "dataset" / "judge_prompt.md"
        if not judge_prompt_path.exists():
            logger.error(f"Judge prompt template not found: {judge_prompt_path}")
            raise typer.Exit(1)

        judge_prompt_template = judge_prompt_path.read_text(encoding="utf-8")
        logger.info(f"Loaded judge prompt template from: {judge_prompt_path}")

        # Load PR dataset
        logger.info("Loading PR dataset...")
        pr_entries = load_pr_dataset()

        if not pr_entries:
            logger.error("No PR entries found in dataset!")
            raise typer.Exit(1)

        logger.info(f"Found {len(pr_entries)} PR entries to evaluate")

        # Create output directory
        output_dir = _config.paths.evaluation_results_path / "pr_review"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Process each PR entry
        results: list[PRReviewResult] = []

        for idx, pr_entry in enumerate(pr_entries):
            logger.info(f"Processing PR {idx + 1}/{len(pr_entries)}: {pr_entry.name}")

            # Build prompt
            prompt = build_pr_security_review_prompt(pr_entry)

            if show_prompts:
                print("\n" + "=" * 80)
                print(f"PR {idx + 1}: {pr_entry.name}")
                print("=" * 80)
                print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
                print("=" * 80 + "\n")

            # Run Copilot CLI
            try:
                cmd_args = [
                    copilot_cmd,
                    "--allow-all-tools",
                    "--allow-all-paths",
                    f"--model={model}",
                    "--log-level=error",  # Reduce noise
                    f"--log-dir={output_dir.resolve()}",
                ]

                result = subprocess.run(
                    cmd_args,
                    input=prompt,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=_config.timeout.github_copilot_cli,
                    text=True,
                    check=False,
                )

                actual_output = result.stdout or ""

                # LLM-based evaluation: Use Copilot CLI as judge
                passed = False
                judge_reason = None
                if actual_output.strip():
                    # Build judge prompt from template
                    expected_comments_json = json.dumps(
                        [{"line": tc["line"], "comment": tc["comment"]} for tc in pr_entry.target_comments],
                        indent=2
                    )
                    judge_prompt = judge_prompt_template.format(
                        expected_comments=expected_comments_json,
                        actual_comments=actual_output
                    )

                    try:
                        judge_result = subprocess.run(
                            [copilot_cmd, f"--model={model}"],
                            input=judge_prompt,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=60,  # Short timeout for judge
                            text=True,
                            check=False,
                        )
                        judge_output = judge_result.stdout.strip()

                        # Try to parse JSON response
                        try:
                            import re
                            # Extract JSON from output (in case there's extra text)
                            json_match = re.search(r'\{.*"passed".*"reason".*\}', judge_output, re.DOTALL)
                            if json_match:
                                judge_data = json.loads(json_match.group(0))
                                passed = judge_data.get("passed", False)
                                judge_reason = judge_data.get("reason", "No reason provided")
                            else:
                                # Fallback to simple true/false check
                                passed = "true" in judge_output.lower()
                                judge_reason = "Failed to parse judge response as JSON"
                        except json.JSONDecodeError:
                            # Fallback to simple true/false check
                            passed = "true" in judge_output.lower()
                            judge_reason = f"Invalid JSON response: {judge_output[:100]}"

                        if show_prompts:
                            print(f"Judge response: {judge_output}")
                            print(f"Parsed - Passed: {passed}, Reason: {judge_reason}")
                    except Exception as judge_error:
                        logger.warning(f"LLM judge failed, defaulting to false: {judge_error}")
                        passed = False
                        judge_reason = f"Judge error: {str(judge_error)}"

                # Create result
                pr_result = PRReviewResult(
                    pr_name=pr_entry.name,
                    pr_description=pr_entry.description,
                    output=actual_output,
                    expected_output=[
                        {"line": tc["line"], "comment": tc["comment"]} for tc in pr_entry.target_comments
                    ],
                    passed=passed,
                    judge_reason=judge_reason,
                    error_message=None if result.returncode == 0 else f"Exit code: {result.returncode}",
                )

                if show_prompts:
                    print(f"Output: {actual_output[:200]}..." if len(actual_output) > 200 else f"Output: {actual_output}")
                    print(f"Result: {'✓ PASS' if passed else '✗ FAIL'}\n")

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout for PR: {pr_entry.name}")
                pr_result = PRReviewResult(
                    pr_name=pr_entry.name,
                    pr_description=pr_entry.description,
                    output="",
                    expected_output=[
                        {"line": tc["line"], "comment": tc["comment"]} for tc in pr_entry.target_comments
                    ],
                    passed=False,
                    judge_reason="Timeout before evaluation",
                    error_message=f"Timeout after {_config.timeout.github_copilot_cli}s",
                )
            except Exception as e:
                logger.error(f"Error processing PR {pr_entry.name}: {e}")
                pr_result = PRReviewResult(
                    pr_name=pr_entry.name,
                    pr_description=pr_entry.description,
                    output="",
                    expected_output=[
                        {"line": tc["line"], "comment": tc["comment"]} for tc in pr_entry.target_comments
                    ],
                    passed=False,
                    judge_reason="Error before evaluation",
                    error_message=str(e),
                )

            results.append(pr_result)

        # Calculate summary statistics
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed

        # Display summary
        print("\n" + "=" * 80)
        print("EVALUATION SUMMARY (LLM Judge)")
        print("=" * 80)
        print(f"Total PRs evaluated: {total}")
        print(f"Passed (covers expected concerns): {passed}")
        print(f"Failed (missing expected concerns): {failed}")
        print(f"Success rate: {(passed / total * 100):.1f}%")
        print("=" * 80 + "\n")

        # Write results to file
        if output_file is None:
            output_file = output_dir / "pr_review_results.jsonl"

        with output_file.open("w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(asdict(result)) + "\n")

        logger.info(f"Results written to: {output_file}")
        print(f"Results saved to: {output_file}")

        # Print detailed results
        print("\nDetailed Results:")
        print("-" * 80)
        for result in results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"{status} | {result.pr_name}")
            if result.judge_reason:
                print(f"  Judge reason: {result.judge_reason}")
            if result.error_message:
                print(f"  Error: {result.error_message}")
            print()

    except Exception as e:
        logger.exception(f"Error running PR review evaluations: {e}")
        raise typer.Exit(1)


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
