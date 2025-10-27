import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig

from bcbench.logger import get_logger
from bcbench.operations.bc_operations import (
    build_ps_app_build_and_publish,
    build_ps_test_script,
)

logger = get_logger(__name__)


@dataclass
class BCEnvironmentConfig(LocalEnvironmentConfig):
    container_name: str = ""
    repo_path: str = ""  # Store as string for JSON serialization
    username: str = "admin"
    password: str = ""
    project_paths: list[str] = field(default_factory=list)
    enable_bc_tools: bool = True  # Flag to show/hide BC-specific tools from agent
    version: str = ""


class BCEnvironment(LocalEnvironment):
    def __init__(self, *, config_class: type = BCEnvironmentConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        self.config: BCEnvironmentConfig = self.config

        if (not self.config.container_name) and self.config.enable_bc_tools:
            raise ValueError("container_name is required in BCEnvironmentConfig when enable_bc_tools is True")
        if not self.config.repo_path:
            raise ValueError("repo_path is required in BCEnvironmentConfig")

    def execute(self, command: str, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = command.strip()

        if command.startswith("bc_build_and_publish "):
            return self._bc_build_and_publish(command, cwd, timeout)
        if command.startswith("bc_test "):
            return self._bc_test(command, cwd, timeout)
        return self._execute_powershell(command, cwd, timeout)

    def _bc_build_and_publish(self, command: str, cwd: str, timeout: int | None) -> dict[str, Any]:
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return {
                "returncode": 1,
                "output": "Error: bc_build_and_publish requires a project path. Usage: bc_build_and_publish <project_path>",
            }

        project_path = parts[1].strip()
        logger.info(f"Building project: {project_path}")

        if self.config.project_paths and (project_path not in self.config.project_paths):
            return {
                "returncode": 1,
                "output": f"Error: Project path '{project_path}' is not in the allowed project_paths list: {self.config.project_paths}",
            }

        full_project_path: Path = Path(self.config.repo_path) / project_path

        ps_script = build_ps_app_build_and_publish(
            container_name=self.config.container_name,
            username=self.config.username,
            password=self.config.password,
            project_path=full_project_path,
            version=self.config.version,
        )

        # Extend timeout for build and publish, especially for BaseApp
        timeout = 15 * 60 if ("BaseApp" in project_path) else 5 * 60

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _bc_test(self, command: str, cwd: str, timeout: int | None) -> dict[str, Any]:
        parts = command.split(maxsplit=2)
        if len(parts) < 2:
            return {
                "returncode": 1,
                "output": "Error: bc_test requires a codeunit ID. Usage: bc_test <codeunit_id> [function1,function2,...]",
            }

        try:
            codeunit_id: int = int(parts[1])
        except ValueError:
            return {
                "returncode": 1,
                "output": f"Error: Invalid codeunit ID '{parts[1]}'. Must be an integer.",
            }

        function_names: list[str] = []
        if len(parts) > 2:
            function_names = [f.strip() for f in parts[2].split(",")]

        if function_names:
            logger.info(f"Running tests: codeunit {codeunit_id}, functions: {', '.join(function_names)}")
        else:
            logger.info(f"Running all tests in codeunit {codeunit_id}")

        ps_script = build_ps_test_script(
            container_name=self.config.container_name,
            username=self.config.username,
            password=self.config.password,
            codeunit_id=codeunit_id,
            function_names=function_names if function_names else None,
        )

        timeout = 2 * 60

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _execute_powershell(self, command: str, cwd: str, timeout: int | None, log_command: bool = True) -> dict[str, Any]:
        """Execute a PowerShell command"""
        if timeout is None:
            timeout = self.config.timeout

        working_dir: str = cwd or self.config.cwd or str(Path.cwd())

        if log_command:
            # Sensitive data redaction is now handled automatically by the logging filter
            command_preview: str = command if len(command) <= 100 else command[:97] + "..."
            logger.info(f"Executing:\n{command_preview}")
            if len(command) > 100:
                logger.debug(f"Full command: {command}")

        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **self.config.env},
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            output_stripped: str = output.strip()
            output_lines: list[str] = output_stripped.split("\n")
            line_count: int = len(output_lines)

            if result.returncode == 0:
                logger.info("Command succeeded")
            else:
                logger.error(f"Command failed with exit code {result.returncode}")
                if line_count > 0:
                    preview_lines = min(3, line_count)
                    logger.error(f"Error output (first {preview_lines} lines):\n{'\n'.join(output_lines[:preview_lines])}")

            # At DEBUG level: show full output (truncated if too long)
            if line_count <= 10:
                logger.debug(f"Full output:\n{output_stripped}")
            else:
                logger.debug(f"Full output ({line_count} lines, showing first/last 5):\n{'\n'.join(output_lines[:5])}\n... ({line_count - 10} lines omitted) ...\n{'\n'.join(output_lines[-5:])}")

            return {"returncode": result.returncode, "output": output_stripped}

        except subprocess.TimeoutExpired as e:
            error_msg = f"Command timed out after {timeout} seconds"
            logger.error(error_msg)
            if e.stdout:
                logger.debug(f"Partial output before timeout:\n{e.stdout}")
            return {
                "returncode": -1,
                "output": f"{error_msg}\n{e.stdout or ''}",
            }
        except Exception as e:
            error_msg = f"Error executing command: {e!s}"
            logger.error(error_msg)
            return {"returncode": -1, "output": error_msg}

    def get_template_vars(self) -> dict[str, Any]:
        """Get template variables for prompt rendering"""
        vars = super().get_template_vars()

        vars.update(
            {
                "container_name": self.config.container_name,
                "repo_path": self.config.repo_path,
                "project_paths": self.config.project_paths,
                "bc_tools_enabled": self.config.enable_bc_tools,
                "version": self.config.version,
            }
        )

        return vars
