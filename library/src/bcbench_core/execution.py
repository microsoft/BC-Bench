from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bcbench_core.results import EvaluationResult, RunIdentity, write_result


class ProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvaluationContext[EntryT]:
    entry: EntryT
    instance_id: str
    workspace: Path
    output_file: Path
    identity: RunIdentity


class AgentRunner[ContextT, OutputT](Protocol):
    def __call__(self, context: ContextT, /) -> OutputT: ...


class EvaluationPipeline[EntryT, OutputT, ResultT: EvaluationResult](Protocol):
    def evaluate(self, context: EvaluationContext[EntryT], agent: AgentRunner[EvaluationContext[EntryT], OutputT]) -> ResultT: ...


def execute[EntryT, OutputT, ResultT: EvaluationResult](
    context: EvaluationContext[EntryT],
    agent: AgentRunner[EvaluationContext[EntryT], OutputT],
    pipeline: EvaluationPipeline[EntryT, OutputT, ResultT],
) -> ResultT:
    result = pipeline.evaluate(context, agent)
    if result.identity != context.identity or result.instance_id != context.instance_id:
        raise ValueError("Pipeline result does not match execution context")
    write_result(context.output_file, result)
    return result


def run_steps[ContextT, OutputT](
    context: ContextT,
    agent: AgentRunner[ContextT, OutputT],
    *,
    setup: Callable[[ContextT], None],
    run_agent: Callable[[ContextT, AgentRunner[ContextT, OutputT]], None],
    evaluate: Callable[[ContextT], None],
    on_timeout: Callable[[ContextT, Exception], None],
    timeout_error: type[Exception],
) -> None:
    setup(context)
    try:
        run_agent(context, agent)
    except timeout_error as error:
        on_timeout(context, error)
        return
    evaluate(context)


def run_command(
    command: Sequence[str],
    *,
    workspace: Path,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    if not command or not (executable := shutil.which(command[0])):
        raise ProviderUnavailableError(f"Agent executable unavailable: {command[0] if command else '(missing)'}")
    return subprocess.run([executable, *command[1:]], cwd=workspace, env=dict(env), timeout=timeout, capture_output=True, text=True, check=True)
