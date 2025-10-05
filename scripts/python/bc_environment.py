import subprocess
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig
from utils import colored, GREY

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

@dataclass
class BCEnvironmentConfig(LocalEnvironmentConfig):
    """Configuration for BC Environment"""
    container_name: str = ""
    nav_repo_path: str = ""
    username: str = "admin"
    password: str = ""
    project_paths: list[str] = field(default_factory=list)
    enable_bc_tools: bool = True  # Flag to hide BC-specific tools from agent

class BCEnvironment(LocalEnvironment):
    def __init__(self, *, config_class: type = BCEnvironmentConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        self.config: BCEnvironmentConfig = self.config

        if not self.config.container_name:
            raise ValueError("container_name is required in BCEnvironmentConfig")
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
        logger.debug(f"Executing command: {command}")
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return {
                "returncode": 1,
                "output": "Error: bc_build requires a project path. Usage: bc_build <project_path>"
            }

        project_path = parts[1].strip()

        if self.config.project_paths and project_path not in self.config.project_paths:
            return {
                "returncode": 1,
                "output": f"Error: Project path '{project_path}' is not in the allowed project_paths list: {self.config.project_paths}"
            }

        full_project_path = os.path.join(self.config.nav_repo_path, project_path)

        # Get the path to AppUtils module (relative to this script)
        script_dir = Path(__file__).parent
        app_utils_path = script_dir.parent / "powershell" / "AppUtils.psm1"

        ps_script = f"""
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '{app_utils_path}' -Force
$ErrorActionPreference = 'Stop'

$projectPath = '{full_project_path}'
$password = ConvertTo-SecureString '{self.config.password}' -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential('{self.config.username}', $password)

Invoke-AppBuildAndPublish -containerName '{self.config.container_name}' -appProjectFolder $projectPath -credential $credential -skipVerification -useDevEndpoint
"""

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _bc_test(self, command: str, cwd: str, timeout: int | None) -> dict[str, Any]:
        logger.debug(f"Executing command: {command}")
        parts = command.split(maxsplit=2)
        if len(parts) < 2:
            return {
                "returncode": 1,
                "output": "Error: bc_test requires a codeunit ID. Usage: bc_test <codeunit_id> [function1,function2,...]"
            }

        try:
            codeunit_id: int = int(parts[1])
        except ValueError:
            return {
                "returncode": 1,
                "output": f"Error: Invalid codeunit ID '{parts[1]}'. Must be an integer."
            }

        function_names: list[str] = []
        if len(parts) > 2:
            function_names = [f.strip() for f in parts[2].split(',')]

        if function_names:
            function_array = ", ".join([f"'{fn}'" for fn in function_names])
            function_param = f"-functionNames @({function_array})"
        else:
            function_param = ""

        # Get the path to AppUtils module (relative to this script)
        script_dir = Path(__file__).parent
        app_utils_path = script_dir.parent / "powershell" / "AppUtils.psm1"

        ps_script = f"""
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '{app_utils_path}' -Force
$ErrorActionPreference = 'Stop'

$password = ConvertTo-SecureString '{self.config.password}' -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential('{self.config.username}', $password)

Write-Host "Running tests for codeunit {codeunit_id}"
Invoke-BCTest -containerName '{self.config.container_name}' -credential $credential -codeunitID {codeunit_id} {function_param}
"""

        return self._execute_powershell(ps_script, cwd or self.config.cwd, timeout, log_command=False)

    def _execute_powershell(self, command: str, cwd: str, timeout: int | None, log_command: bool = True) -> dict[str, Any]:
        """Execute a PowerShell command"""
        if timeout is None:
            timeout = self.config.timeout

        working_dir: str = cwd or self.config.cwd or os.getcwd()

        if log_command:
            logger.debug(f"Executing command: `{colored(command, GREY)}`")

        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **self.config.env}
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            # Log output in a more manageable way
            output_stripped: str = output.strip()
            output_lines: list[str] = output_stripped.split('\n')
            line_count: int = len(output_lines)

            if line_count <= 6:
                logger.debug(colored(f"Output:\n{output_stripped}", GREY))
            else:
                logger.debug(colored(f"Output ({line_count} lines, showing first/last 3):\n{"\n".join(output_lines[:3])}\n... (other lines omitted) ...\n{"\n".join(output_lines[-3:])}", GREY))

            return {
                "returncode": result.returncode,
                "output": output_stripped
            }

        except subprocess.TimeoutExpired as e:
            return {
                "returncode": -1,
                "output": f"Command timed out after {timeout} seconds\n{e.stdout or ''}"
            }
        except Exception as e:
            return {
                "returncode": -1,
                "output": f"Error executing command: {str(e)}"
            }

    def get_template_vars(self) -> dict[str, Any]:
        """Get template variables for prompt rendering"""
        vars = super().get_template_vars()

        vars.update({
            "container_name": self.config.container_name,
            "nav_repo_path": self.config.nav_repo_path,
            "project_paths": self.config.project_paths,
            "bc_tools_enabled": self.config.enable_bc_tools,
        })

        return vars
