"""Harness-neutral contract for evaluating one task: prepare its workspace, run the agent, grade the outcome.

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


class Category[C, R](Protocol):
    """Prepares a task for an agent and grades its work into a result of type ``R``.

    Categories hold only configuration; everything about one evaluation (the task, its workspace and so on) comes in
    its context of type ``C``. ``grade`` returns a result for every agent-attributable outcome and raises only for infrastructure or
    dataset errors, which must fail the evaluation.
    """

    def prepare_workspace(self, context: C) -> None:
        """Prepare what the agent sees, without building; used to only run the agent."""
        ...

    def prepare(self, context: C) -> None:
        """Prepare for a full evaluation, which may build; owns the ordering of all setup steps."""
        ...

    def grade(self, context: C, result: AgentResult) -> R: ...


def evaluate_task[C, A, R, N: str](
    category: Category[C, R],
    context: C,
    harness: AgentHarness[A, N],
    request: AgentRequest[A],
    *,
    on_timeout: Callable[[C, AgentResult], R],
) -> R:
    """Prepare the task in ``context``, run the agent on ``request`` and grade its work.

    A timed-out agent is not graded: ``on_timeout`` scores it from what was observed before it was stopped
    (never a response). Any other ``AgentError`` propagates: the attempt could not be evaluated.
    """
    category.prepare(context)

    try:
        result: AgentResult = harness.run(request)
    except AgentTimeoutError as e:
        observed = AgentResult(metrics=e.metrics, experiment=e.config, transcript=e.transcript)
        _log_result(observed)
        logger.info("Agent timed out during execution, counting as failure.")
        return on_timeout(context, observed)
    except AgentError:
        logger.exception("Agent execution failed")
        raise

    _log_result(result)
    return category.grade(context, result)


def _log_result(result: AgentResult) -> None:
    logger.info(f"Agent metrics: {result.metrics}")
    logger.info(f"Experiment configuration: {result.experiment}")
