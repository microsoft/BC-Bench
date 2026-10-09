from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.nl2al.pipeline import NL2ALPipeline
from bcbench.dataset import NL2ALEntry
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[NL2ALEntry] = CategoryDefinition(
    category=EvaluationCategory.NL2AL,
    dataset_file="nl2al.jsonl",
    entry_type=NL2ALEntry,
    make_pipeline=NL2ALPipeline,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="windows-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
