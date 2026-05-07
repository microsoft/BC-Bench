"""bc-al agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import os
import subprocess
import time
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_FRAMEWORK = "net10.0"
_AUDIENCE = "both"
_PAGE = "Customer Card"

_init_env: dict[str, str] | None = None


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise AgentError(f"Environment variable {name} is required but not set. Add it to your .env file.")
    return value


def _get_bcal_repo() -> Path:
    return Path(_require_env("BCAL_REPO_PATH"))


def _get_bcal_project() -> Path:
    return _get_bcal_repo() / "source" / "Prod" / "bcal" / "bcal.cli.csproj"


def _get_init_env() -> dict[str, str]:
    """Run init.ps1 in the BC-DeveloperExperience repo and capture the resulting environment."""
    global _init_env  # noqa: PLW0603
    if _init_env is not None:
        return _init_env

    bcal_repo = _get_bcal_repo()
    init_script = bcal_repo / "init.ps1"
    if not init_script.exists():
        raise AgentError(f"init.ps1 not found at: {init_script}")

    # Run init.ps1, then dump env vars in a delimited block to separate from init.ps1 output
    marker = "___BCBENCH_ENV_START___"
    ps_command = (
        f"Set-Location '{bcal_repo}'; "
        f". '.\\init.ps1' | Out-Null; "
        f"Write-Output '{marker}'; "
        f"Get-ChildItem Env: | ForEach-Object {{ \"$($_.Name)=$($_.Value)\" }}"
    )

    logger.info("Running init.ps1 to capture build environment...")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
        cwd=str(bcal_repo),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    if result.returncode != 0:
        raise AgentError(f"init.ps1 failed (exit {result.returncode}): {result.stderr}")

    # Extract env vars after the marker
    stdout = result.stdout
    if marker not in stdout:
        raise AgentError(f"init.ps1 output did not contain expected marker. stdout: {stdout[:500]}")

    env_block = stdout.split(marker, 1)[1].strip()
    env = dict(os.environ)
    for line in env_block.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            env[key] = value

    _init_env = env
    logger.info(f"Captured {len(env)} environment variables from init.ps1 (INETROOT={env.get('INETROOT', '<not set>')})")
    return _init_env


def run_bcal_agent(
    entry: NL2ALEntry,
    output_dir: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    bcal_repo = _get_bcal_repo()
    bcal_project = _get_bcal_project()
    azure_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    azure_deployment = _require_env("AZURE_OPENAI_DEPLOYMENT")

    if not bcal_project.exists():
        raise AgentError(f"bcal CLI project not found at: {bcal_project}")

    env = _get_init_env()
    logger.info(f"Running bcal CLI on: {entry.instance_id}")

    prompt = entry.nl_prompt

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name = entry.project_paths[0] if entry.project_paths else "App"
    package_cache_path = output_dir / project_name / ".alpackages"
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    # Export folder for generated AL files
    export_folder = output_dir / project_name / "src"
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        "dotnet",
        "run",
        "--framework",
        _FRAMEWORK,
        "--project",
        str(bcal_project),
        "--packagecachepath",
        str(package_cache_path),
        "--endpoint",
        azure_endpoint,
        "--deployment",
        azure_deployment,
        "--audience",
        _AUDIENCE,
        "--page",
        _PAGE,
        "--prompt",
        prompt,
        "--exportfolder",
        str(export_folder),
    ]

    logger.info(f"Executing bcal CLI from: {bcal_repo}")
    logger.info(f"Package cache path: {package_cache_path}")
    logger.info(f"Export folder: {export_folder}")
    logger.debug(f"Using prompt:\n{prompt}")
    logger.debug(f"bcal CLI command: {cmd_args}")

    try:
        start = time.monotonic()
        subprocess.run(
            cmd_args,
            cwd=str(bcal_repo),
            env=env,
            timeout=_config.timeout.agent_execution,
            check=True,
        )
        execution_time = time.monotonic() - start

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentMetrics(execution_time=execution_time), ExperimentConfiguration()
    except subprocess.TimeoutExpired:
        logger.exception(f"bcal CLI timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"bcal CLI execution failed: {e.stderr}")
        raise AgentError(f"bcal CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running bcal CLI")
        raise
