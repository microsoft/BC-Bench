from __future__ import annotations

import logging
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from bcbench_core.agents.copilot.cli import get_copilot_version, invoke_copilot
from bcbench_core.evaluation import EvaluationRequest
from bcbench_core.exceptions import AgentError
from bcbench_core.types import AgentExecution, AgentMetrics, AgentMetricsContract, DatasetEntry, ExperimentConfiguration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CopilotSettings:
    timeout: int
    allow_all_tools: bool = True
    pass_environment: Mapping[str, str] | None = None


@dataclass(frozen=True)
class PreparedCopilotExtension:
    arguments: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    mcp_servers: tuple[str, ...] = ()
    al_lsp_enabled: bool = False
    custom_instructions: bool = False
    skills_enabled: bool = False
    custom_agent: str | None = None
    plugins: tuple[str, ...] = ()


class CopilotExtension[E: DatasetEntry](Protocol):
    def prepare(self, request: EvaluationRequest[E]) -> PreparedCopilotExtension: ...

    def close(self) -> None: ...


class CopilotHarness[E: DatasetEntry]:
    name = "GitHub Copilot"
    metrics_contract = AgentMetricsContract(
        AgentMetrics,
        frozenset({"execution_time", "llm_duration", "ai_credits", "turn_count", "tool_usage"}),
    )

    def __init__(self, settings: CopilotSettings, extensions: Sequence[CopilotExtension[E]] = ()) -> None:
        self._settings = settings
        self._extensions = tuple(extensions)
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        if self._version is None:
            self._version = get_copilot_version()
        return self._version

    def run(self, request: EvaluationRequest[E]) -> AgentExecution:
        prepared: list[PreparedCopilotExtension] = []
        active_extensions: list[CopilotExtension[E]] = []
        try:
            for extension in self._extensions:
                try:
                    prepared.append(extension.prepare(request))
                except Exception:
                    extension.close()
                    raise
                active_extensions.append(extension)

            arguments = tuple(argument for extension in prepared for argument in extension.arguments)
            environment = dict(self._settings.pass_environment or {})
            for extension in prepared:
                environment.update(extension.environment)
            experiment = ExperimentConfiguration(
                mcp_servers=list(dict.fromkeys(server for extension in prepared for server in extension.mcp_servers)) or None,
                al_lsp_enabled=any(extension.al_lsp_enabled for extension in prepared),
                custom_instructions=any(extension.custom_instructions for extension in prepared),
                skills_enabled=any(extension.skills_enabled for extension in prepared),
                custom_agent=next((extension.custom_agent for extension in prepared if extension.custom_agent), None),
                plugins=list(dict.fromkeys(plugin for extension in prepared for plugin in extension.plugins)) or None,
            )
            metrics, _ = invoke_copilot(
                prompt=request.prompt,
                model=request.model,
                work_dir=request.repo_path,
                timeout=self._settings.timeout,
                allow_all_tools=self._settings.allow_all_tools,
                custom_instructions=experiment.custom_instructions,
                extra_args=arguments,
                env=environment or None,
            )
        except subprocess.TimeoutExpired:
            logger.exception("Copilot CLI timed out after %s seconds", self._settings.timeout)
            return AgentExecution(
                metrics=AgentMetrics(execution_time=self._settings.timeout),
                experiment=experiment,
                timed_out=True,
            )
        except subprocess.CalledProcessError as error:
            raise AgentError(f"Copilot CLI execution failed: {error}") from error
        finally:
            for extension in reversed(active_extensions):
                extension.close()
        return AgentExecution(metrics=metrics, experiment=experiment)
