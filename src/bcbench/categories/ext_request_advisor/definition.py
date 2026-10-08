from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_advisor.pipeline import ExtRequestAdvisorPipeline
from bcbench.dataset import ExtRequestAdvisorEntry
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestAdvisorEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_ADVISOR,
    dataset_file="extensibility_request_advisor.jsonl",
    entry_type=ExtRequestAdvisorEntry,
    make_pipeline=ExtRequestAdvisorPipeline,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
