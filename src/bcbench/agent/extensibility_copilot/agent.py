"""GitHub Copilot CLI Agent implementation."""

import shutil
import subprocess
import sys
from pathlib import Path
import threading

import yaml

from bcbench.agent.extensibility_copilot.mcp import build_mcp_config
from bcbench.agent.extensibility_copilot.metrics import parse_metrics
from bcbench.agent.extensibility_copilot.prompt import build_prompt
from bcbench.config import get_config
from bcbench.dataset import DatasetEntryV2
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations import setup_instructions_from_config

logger = get_logger(__name__)
_config = get_config()


def run_copilot_agent(entry: DatasetEntryV2, repo_path, model: str, output_dir: Path) -> tuple[dict[str, float | int] | None, list[str] | None, bool]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Dictionary containing metrics extracted from the CLI output, or None if collection fails
        List of MCP server names used in the experiment, or None if no MCP servers configured
        Boolean indicating if custom instructions were enabled
    """
    config_file = Path(__file__).parent / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, copilot_config)
    mcp_config_json, mcp_server_names = build_mcp_config(copilot_config, repo_path)
    instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path, Path(__file__).parent)

    logger.info(f"Executing Copilot CLI in directory: {repo_path}. Instructions enabled: {instructions_enabled}")
    logger.debug(f"Using prompt:\n{prompt}")

    copilot_cmd = shutil.which("copilot")  # Resolve the copilot command path
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    try:
        cmd_args = [
            copilot_cmd,
            "--allow-all-tools",  # required for non-interactive mode
            "--allow-all-paths",  # might be required for non-interactive mode, seems to hang when trying to access files outside allowed dirs
            "--disable-builtin-mcps",
            f"--model={model}",
            "--log-level=debug",
            f"--log-dir={output_dir.resolve() / entry.instance_id}",
            "--prompt", prompt.replace("\r", " ").replace("\n", " ").replace('"', "'"),
        ]
        if not instructions_enabled:
            cmd_args.append("--no-custom-instructions")
        if mcp_config_json:
            cmd_args.append(f"--additional-mcp-config={mcp_config_json}")

        logger.debug(f"Copilot command args: {cmd_args}")

        proc = subprocess.Popen(
            cmd_args,
            cwd=str(repo_path),
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        stdout_buf = []
        stderr_buf = []

        def stream_output(pipe, buffer, prefix=""):
            for line in pipe:
                sys.stdout.write(prefix + line)   # show live
                buffer.append(line)               # capture
            pipe.close()

        t1 = threading.Thread(target=stream_output, args=(proc.stdout, stdout_buf, "[OUT] "))
        t2 = threading.Thread(target=stream_output, args=(proc.stderr, stderr_buf, "[ERR] "))

        t1.start()
        t2.start()

        try:
            proc.wait(timeout=_config.timeout.github_copilot_cli)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")

        t1.join()
        t2.join()

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=proc.returncode,
                cmd=proc.args
            )

        log_contents = ""
        for log_file_path in (output_dir / entry.instance_id).glob("*.log"):
            with open(log_file_path, "r", encoding="utf-8", errors="replace") as log_file:
                log_contents += log_file.read() + "\n"

        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")

        return parse_metrics(stderr_buf + stdout_buf + [log_contents]), mcp_server_names, instructions_enabled
    except subprocess.TimeoutExpired:
        # timeout should not raise an exception, we will evaluate whatever copilot did so far
        logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")
        return None, mcp_server_names, instructions_enabled
    except subprocess.CalledProcessError as e:
        logger.error(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception as e:
        logger.exception(f"Unexpected error running Copilot CLI: {e}")
        raise
