from dataclasses import dataclass
from pathlib import Path

from bcbench_core.filesystem import prepare_run_dir

from bcbench.categories.base import CategoryDefinition, JudgeCategoryDefinition
from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.evaluate.base import AgentRunner
from bcbench.types import AgentHarness, ContainerConfig, EvaluationContext


@dataclass(frozen=True, kw_only=True)
class EvaluationRequest:
    entry_id: str
    repo_path: Path
    output_dir: Path
    container: ContainerConfig | None = None


@dataclass(frozen=True, kw_only=True)
class AgentSelection[E: BaseDatasetEntry]:
    name: AgentHarness
    model: str
    runner: AgentRunner[E]
    version: str | None = None


def _context[E: BaseDatasetEntry](definition: CategoryDefinition[E], request: EvaluationRequest, agent: AgentSelection[E], result_dir: Path) -> EvaluationContext[E]:
    entry = definition.entry_class.load(definition.dataset_path, entry_id=request.entry_id)[0]
    return EvaluationContext(
        entry=entry,
        repo_path=request.repo_path,
        result_dir=result_dir,
        agent_name=agent.name,
        model=agent.model,
        agent_version=agent.version,
        category=definition.name,
        container=request.container,
        judge_model=definition.judge_model if isinstance(definition, JudgeCategoryDefinition) else None,
    )


def run_entry[E: BaseDatasetEntry](definition: CategoryDefinition[E], request: EvaluationRequest, agent: AgentSelection[E]) -> EvaluationContext[E]:
    context = _context(definition, request, agent, request.output_dir)
    definition.pipeline_factory().setup_workspace(context.entry, context.repo_path)
    context.metrics, context.experiment = agent.runner(context)
    return context


def evaluate_entry[E: BaseDatasetEntry](definition: CategoryDefinition[E], request: EvaluationRequest, agent: AgentSelection[E], *, run_id: str) -> EvaluationContext[E]:
    if definition.capabilities.requires_container and request.container is None:
        raise ValueError(f"The {definition.name.value} category requires a container")
    context = _context(definition, request, agent, request.output_dir / run_id)
    context.result_dir = prepare_run_dir(request.output_dir, run_id)
    definition.pipeline_factory().execute(context, agent.runner)
    return context
