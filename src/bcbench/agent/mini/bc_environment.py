import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig

from bcbench.config import get_config
from bcbench.exceptions import ConfigurationError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


@dataclass
class BCEnvironmentConfig(LocalEnvironmentConfig):
    repo_path: str = ""  # Store as string for JSON serialization
    include_project_paths: bool = False
    project_paths: list[str] = field(default_factory=list)
    version: str = ""


class BCEnvironment(LocalEnvironment):
    def __init__(self, *, config_class: type = BCEnvironmentConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        self.config: BCEnvironmentConfig = self.config

        if not self.config.repo_path:
            raise ConfigurationError("repo_path is required in BCEnvironmentConfig")

    def execute(self, command: str, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = command.strip()
        return self._execute_powershell(command, cwd, timeout)

    def _execute_powershell(self, command: str, cwd: str, timeout: int | None, log_command: bool = True) -> dict[str, Any]:
        """Execute a PowerShell command"""
        if timeout is None:
            timeout = self.config.timeout

        working_dir: str = cwd or self.config.cwd or str(Path.cwd())

        if log_command:
            command_preview: str = command if len(command) <= 100 else command[:97] + "..."
            logger.info(f"Executing:\n{command_preview}")

        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                env={**os.environ, **self.config.env},
            )
            logger.info("Command succeeded")
            return {"returncode": result.returncode, "output": (result.stdout).strip()}

        except subprocess.TimeoutExpired as e:
            error_msg = f"Command timed out after {timeout} seconds"
            logger.warning(error_msg)

            return {
                "returncode": -1,
                "output": f"{error_msg}\n{e.stdout or ''}",
            }
        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed with exit code {e.returncode}"
            logger.warning(error_msg)
            if e.stderr and log_command:
                logger.debug(f"Error output (first line):\n{e.stderr.splitlines()[0]}")

            return {"returncode": e.returncode, "output": f"{error_msg}\n{e.stdout or ''}{e.stderr or ''}".strip()}
        except Exception as e:
            error_msg = f"Error executing command: {e!s}"
            logger.warning(error_msg)
            return {"returncode": -1, "output": error_msg}

    def get_template_vars(self) -> dict[str, Any]:
        """Get template variables for prompt rendering"""
        vars = super().get_template_vars()

        vars.update(
            {
                "repo_path": self.config.repo_path,
                "project_paths": self.config.project_paths,
                "include_project_paths": self.config.include_project_paths,
                "version": self.config.version,
            }
        )

        return vars
