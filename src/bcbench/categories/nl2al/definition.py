from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import NL2ALEntry
from bcbench.types import EvaluationCategory

DEFINITION = CategoryDefinition(
    category=EvaluationCategory.NL2AL,
    dataset_file="nl2al.jsonl",
    entry_type=NL2ALEntry,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="windows-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
