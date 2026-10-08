from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import TestGenEntry
from bcbench.types import EvaluationCategory

DEFINITION = CategoryDefinition(
    category=EvaluationCategory.TEST_GENERATION,
    dataset_file="bcbench.jsonl",
    entry_type=TestGenEntry,
    evaluators=("resolution_rate", "build_rate", "pre_patch_failed_rate", "post_patch_passed_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=True,
)
