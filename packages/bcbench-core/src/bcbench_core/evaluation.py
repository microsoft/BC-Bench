"""Harness-neutral contract for evaluating one task: prepare the workspace, run the agent, grade the outcome.

Applications implement ``Category`` once per kind of task; which categories exist, their datasets and their
result types are application policy and stay out of this package.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from bcbench_core.agent.harness import AgentHarness, AgentRequest, AgentResult
from bcbench_core.exceptions import AgentError, AgentTimeoutError

__all__ = ["Category", "evaluate_task"]

logger = logging.getLogger(__name__)


class Category[T, R](Protocol):
    """Prepares tasks of type ``T`` for an agent and grades its work into results of type ``R``.

    Categories hold only configuration; everything about one evaluation, including its workspace, comes with the
    task. ``grade`` returns a result for every agent-attributable outcome and raises only for infrastructure or
    dataset errors, which must fail the evaluation.
    """

    def prepare_workspace(self, task: T) -> None:
        """Prepare what the agent sees, without building; used to only run the agent."""
        ...

    def prepare(self, task: T) -> None:
        """Prepare for a full evaluation, which may build; owns the ordering of all setup steps."""
        ...

    def grade(self, task: T, result: AgentResult) -> R: ...


def evaluate_task[T, A, R, N: str](
    category: Category[T, R],
    task: T,
    harness: AgentHarness[A, N],
    request: AgentRequest[A],
    *,
    on_timeout: Callable[[T, AgentResult], R],
) -> R:
    """Prepare, run the agent on ``request`` and grade ``task``.

    A timed-out agent is not graded: ``on_timeout`` scores it from what was observed before it was stopped
    (never a response). Any other ``AgentError`` propagates: the attempt could not be evaluated.
    """
    category.prepare(task)

    try:
        result: AgentResult = harness.run(request)
    except AgentTimeoutError as e:
        observed = AgentResult(metrics=e.metrics, experiment=e.config, transcript=e.transcript)
        _log_result(observed)
        logger.info("Agent timed out during execution, counting as failure.")
        return on_timeout(task, observed)
    except AgentError:
        logger.exception("Agent execution failed")
        raise

    _log_result(result)
    return category.grade(task, result)


def _log_result(result: AgentResult) -> None:
    logger.info(f"Agent metrics: {result.metrics}")
    logger.info(f"Experiment configuration: {result.experiment}")
