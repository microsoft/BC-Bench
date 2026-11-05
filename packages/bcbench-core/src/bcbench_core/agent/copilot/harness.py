"""Copilot CLI behind the harness contract, configured once for every prompt it runs."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import override

from bcbench_core.agent.copilot.agent import get_copilot_version, invoke_copilot
from bcbench_core.agent.copilot.types import CopilotOptions, CopilotTimeoutError
from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentIdentity, AgentRequest, AgentResult, Harness
from bcbench_core.exceptions import AgentTimeoutError

__all__ = ["CopilotHarness"]


@dataclass(frozen=True)
class CopilotHarness[N: str = str](Harness[str, N]):
    """Runs a prompt through Copilot CLI with fixed options; the task is the prompt itself.

    ``CopilotOptions()`` answers from the prompt alone (no tools, no custom instructions).
    Debug logs go to ``request.output_dir``; ``options.log_dir`` is ignored.
    """

    name: N
    model: str
    env: Mapping[str, str]
    options: CopilotOptions = field(default_factory=CopilotOptions)
    # Reported with every result and timeout
    experiment: ExperimentConfiguration | None = None
    timeout: int = 30 * 60

    @override
    def identity(self) -> AgentIdentity[N]:
        # Validating against the unparametrized model would coerce a StrEnum name to a plain str
        return AgentIdentity[N].model_construct(harness=self.name, version=get_copilot_version(), model=self.model)

    @override
    def run(self, request: AgentRequest[str], /) -> AgentResult:
        try:
            metrics, response = invoke_copilot(
                prompt=request.task,
                model=self.model,
                work_dir=request.work_dir,
                timeout=self.timeout if request.timeout is None else request.timeout,
                env=self.env,
                options=replace(self.options, log_dir=request.output_dir),
            )
        except CopilotTimeoutError as exc:
            raise AgentTimeoutError(str(exc), metrics=exc.metrics, config=self.experiment) from exc
        return AgentResult(response=response, metrics=metrics, experiment=self.experiment)
