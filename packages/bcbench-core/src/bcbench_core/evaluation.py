import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from bcbench_core.results import EvaluationResult

logger = logging.getLogger(__name__)


class AgentRunner[C, M, X](Protocol):
    def __call__(self, context: C, /) -> tuple[M | None, X | None]: ...


class EvaluationPipeline[C, M, X, R: EvaluationResult](ABC):
    @abstractmethod
    def setup(self, context: C) -> None:
        raise NotImplementedError

    @abstractmethod
    def run_agent(self, context: C, agent_runner: AgentRunner[C, M, X]) -> None:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, context: C) -> None:
        raise NotImplementedError

    @abstractmethod
    def result_path(self, context: C, result: R) -> Path:
        raise NotImplementedError

    def handle_agent_timeout(self, context: C, error: TimeoutError) -> None:
        raise error

    def after_agent(self, context: C) -> None:
        logger.debug("Agent execution finished")

    def execute(self, context: C, agent_runner: AgentRunner[C, M, X]) -> None:
        self.setup(context)
        try:
            self.run_agent(context, agent_runner)
        except TimeoutError as error:
            self.handle_agent_timeout(context, error)
            return
        finally:
            self.after_agent(context)

        self.evaluate(context)

    def save_result(self, context: C, result: R) -> None:
        path = self.result_path(context, result)
        result.save(path.parent, path.name)
