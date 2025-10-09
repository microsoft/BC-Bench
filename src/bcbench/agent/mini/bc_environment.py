import subprocess
import os
import re
from dataclasses import dataclass, field
from typing import Any
from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig
from bcbench.core.logger import get_logger
from bcbench.core.bc_operations import build_ps_app_build_and_publish, build_ps_test_script

logger = get_logger(__name__)


@dataclass
class BCEnvironmentConfig(LocalEnvironmentConfig):
    container_name: str = ""
    nav_repo_path: str = ""
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
        if not self.config.nav_repo_path:
            raise ValueError("nav_repo_path is required in BCEnvironmentConfig")

    def execute(self, command: str, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = command.strip()

        if command.startswith("bc_build "):
            return self._bc_build(command, cwd, timeout)
        elif command.startswith("bc_test "):
            return self._bc_test(command, cwd, timeout)
        else:
            return self._execute_powershell(command, cwd, timeout)

    def _bc_build(self, command: str, cwd: str, timeout: int | None) -> dict[str, Any]:
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return {"returncode": 1, "output": "Error: bc_build requires a project path. Usage: bc_build <project_path>"}

        project_path = parts[1].strip()
        logger.info(f"Building project: {project_path}")

        if self.config.project_paths and project_path not in self.config.project_paths:
            return {"returncode": 1, "output": f"Error: Project path '{project_path}' is not in the allowed project_paths list: {self.config.project_paths}"}

        full_project_path = os.path.join(self.config.nav_repo_path, project_path)

        ps_script = build_ps_app_build_and_publish(
            container_name=self.config.container_name,
            username=self.config.username,
            password=self.config.password,
            project_path=full_project_path,
            version=self.config.version,
        )

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _bc_test(self, command: str, cwd: str, timeout: int | None) -> dict[str, Any]:
        parts = command.split(maxsplit=2)
        if len(parts) < 2:
            return {"returncode": 1, "output": "Error: bc_test requires a codeunit ID. Usage: bc_test <codeunit_id> [function1,function2,...]"}

        try:
            codeunit_id: int = int(parts[1])
        except ValueError:
            return {"returncode": 1, "output": f"Error: Invalid codeunit ID '{parts[1]}'. Must be an integer."}

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

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _execute_powershell(self, command: str, cwd: str, timeout: int | None, log_command: bool = True) -> dict[str, Any]:
        """Execute a PowerShell command"""
        if timeout is None:
            timeout = self.config.timeout

        working_dir: str = cwd or self.config.cwd or os.getcwd()

        if log_command:
            # Redact password assignments in the command string when logging
            def redact_passwords(cmd: str) -> str:
                # Replace e.g. $password = ConvertTo-SecureString '...'
                # Supports both single and double quotes
                return re.sub(
                    r"(\$password\s*=\s*ConvertTo-SecureString\s*['\"])[^'\"]*(['\"]\s*-AsPlainText\s*-Force)",
                    r"\1******\2",
                    cmd,
                )

            redacted_command = redact_passwords(command)
            command_preview: str = redacted_command if len(redacted_command) <= 100 else redacted_command[:97] + "..."
            logger.info(f"Executing:\n{command_preview}")
            if len(redacted_command) > 100:
                logger.debug(f"Full command: {redacted_command}")

        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], cwd=working_dir, capture_output=True, text=True, timeout=timeout, env={**os.environ, **self.config.env}
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            output_stripped: str = output.strip()
            output_lines: list[str] = output_stripped.split("\n")
            line_count: int = len(output_lines)

            # At INFO level: show return code and line count for successful commands, first 3 lines for errors
            if result.returncode == 0:
                logger.info(f"Command succeeded ({line_count} lines of output)")
            else:
                logger.info(f"Command failed with exit code {result.returncode}")
                if line_count > 0:
                    preview_lines = min(3, line_count)
                    logger.info(f"Error output (first {preview_lines} lines):\n{'\n'.join(output_lines[:preview_lines])}")

            # At DEBUG level: show full output (truncated if too long)
            if line_count <= 10:
                logger.debug(f"Full output:\n{output_stripped}")
            else:
                logger.debug(f"Full output ({line_count} lines, showing first/last 5):\n{'\n'.join(output_lines[:5])}\n... ({line_count - 10} lines omitted) ...\n{'\n'.join(output_lines[-5:])}")

            return {"returncode": result.returncode, "output": output_stripped}

        except subprocess.TimeoutExpired as e:
            return {"returncode": -1, "output": f"Command timed out after {timeout} seconds\n{e.stdout or ''}"}
        except Exception as e:
            return {"returncode": -1, "output": f"Error executing command: {str(e)}"}

    def get_template_vars(self) -> dict[str, Any]:
        """Get template variables for prompt rendering"""
        vars = super().get_template_vars()

        vars.update(
            {
                "container_name": self.config.container_name,
                "nav_repo_path": self.config.nav_repo_path,
                "project_paths": self.config.project_paths,
                "bc_tools_enabled": self.config.enable_bc_tools,
                "version": self.config.version,
            }
        )

        return vars
