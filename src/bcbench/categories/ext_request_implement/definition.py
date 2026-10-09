from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_implement.pipeline import ExtRequestImplementPipeline
from bcbench.dataset import ExtRequestImplementEntry
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestImplementEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_IMPLEMENT,
    dataset_file="extensibility_request_implement.jsonl",
    entry_type=ExtRequestImplementEntry,
    make_pipeline=ExtRequestImplementPipeline,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
