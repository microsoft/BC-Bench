"""Simple script to run PR security review with Copilot CLI and print results."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.agent.pr_security_review_helper import build_pr_security_review_prompt, load_pr_dataset
from bcbench.config import get_config
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def run_pr_security_review_demo():
    """Demo: Run security review on first PR entry and show the prompt."""
    try:
        # Load PR dataset
        logger.info("Loading PR dataset...")
        pr_entries = load_pr_dataset()

        if not pr_entries:
            logger.error("No PR entries found in dataset!")
            return

        # Take first entry
        pr_entry = pr_entries[0]
        logger.info(f"Loaded PR: {pr_entry.name}")

        # Build complete prompt with instructions and PR data
        logger.info("Building security review prompt...")
        prompt = build_pr_security_review_prompt(pr_entry)

        # Print the prompt (this is what will be sent to the AI agent)
        print("\n" + "=" * 80)
        print("SECURITY REVIEW PROMPT FOR AI AGENT")
        print("=" * 80)
        print(prompt)
        print("=" * 80)

        # Print target comments for reference
        print("\n" + "=" * 80)
        print("TARGET COMMENTS (Expected AI Output)")
        print("=" * 80)
        for i, target in enumerate(pr_entry.target_comments, 1):
            print(f"{i}. Line {target['line']}: {target['comment']}")
        print("=" * 80 + "\n")

        logger.info(f"Total target comments expected: {len(pr_entry.target_comments)}")

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception(f"Error: {e}")
        raise typer.Exit(1)


def run_pr_review_with_copilot(entry_index: int = 0, output_file: Path | None = None):
    """Run PR security review with Copilot CLI.

    Args:
        entry_index: Index of PR entry to review (0-based)
        output_file: Optional file to save the prompt to
    """
    import subprocess
    import shutil

    try:
        # Load PR dataset
        logger.info("Loading PR dataset...")
        pr_entries = load_pr_dataset()

        if not pr_entries:
            logger.error("No PR entries found in dataset!")
            return

        if entry_index >= len(pr_entries):
            logger.error(f"Entry index {entry_index} out of range. Available: {len(pr_entries)}")
            return

        # Get entry
        pr_entry = pr_entries[entry_index]
        logger.info(f"Selected PR: {pr_entry.name}")

        # Build complete prompt
        logger.info("Building security review prompt...")
        prompt = build_pr_security_review_prompt(pr_entry)

        # Optionally save prompt to file
        if output_file:
            output_file = Path(output_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with output_file.open("w") as f:
                f.write(prompt)
            logger.info(f"Prompt saved to: {output_file}")

        # Check if Copilot CLI is available
        copilot_cmd = shutil.which("copilot")
        if not copilot_cmd:
            logger.warning("Copilot CLI not found. Showing prompt instead.")
            print("\n" + "=" * 80)
            print("PROMPT FOR COPILOT CLI")
            print("=" * 80)
            print(prompt)
            print("=" * 80)
            logger.info("Install Copilot CLI to run actual agent: npm install -g @github/copilot")
            return

        # Run Copilot CLI
        logger.info("Running Copilot CLI...")
        print("\n" + "=" * 80)
        print("RUNNING COPILOT CLI")
        print("=" * 80)

        cmd_args = [
            copilot_cmd,
            "--allow-all-tools",
            "--model=claude-haiku-4.5",
            "--log-level=debug",
            f"--prompt={prompt.replace(chr(10), ' ')}",
        ]

        result = subprocess.run(cmd_args, capture_output=False, timeout=60)

        if result.returncode == 0:
            logger.info("Copilot CLI completed successfully")
        else:
            logger.warning(f"Copilot CLI exited with code {result.returncode}")

        print("=" * 80 + "\n")

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception(f"Error: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app = typer.Typer()

    @app.command()
    def demo():
        """Show the security review prompt (without running agent)."""
        run_pr_security_review_demo()

    @app.command()
    def run(
        index: Annotated[int, typer.Option(help="PR entry index to review (0-based)")] = 0,
        output: Annotated[Path | None, typer.Option(help="Save prompt to file")] = None,
    ):
        """Run security review with Copilot CLI."""
        run_pr_review_with_copilot(index, output)

    app()
