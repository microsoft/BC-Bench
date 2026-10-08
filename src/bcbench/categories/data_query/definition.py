from bcbench.categories.data_query.pipeline import DataQueryPipeline
from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import DataQueryEntry
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[DataQueryEntry] = CategoryDefinition(
    category=EvaluationCategory.DATA_QUERY,
    dataset_file="dataquery.jsonl",
    entry_type=DataQueryEntry,
    make_pipeline=DataQueryPipeline,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=False,
)
