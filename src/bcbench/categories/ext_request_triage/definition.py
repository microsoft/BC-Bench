from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_triage.pipeline import ExtRequestTriagePipeline
from bcbench.dataset import ExtRequestTriageEntry
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestTriageEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_TRIAGE,
    dataset_file="extensibility_request_triage.jsonl",
    entry_type=ExtRequestTriageEntry,
    make_pipeline=ExtRequestTriagePipeline,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
