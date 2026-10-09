from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import BugFixEntry
from bcbench.types import EvaluationCategory

DEFINITION = CategoryDefinition(
    category=EvaluationCategory.BUG_FIX,
    dataset_file="bcbench.jsonl",
    entry_type=BugFixEntry,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=True,
)
