import json
import logging
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, override

from bcbench_core.agent.harness import AgentResult
from bcbench_core.evaluation import Category
from bcbench_core.filesystem import clear_directory
from pydantic import Field

from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import EmptyGoldResultError
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import DatasetTier, EvaluationCategory, EvaluationContext

logger = logging.getLogger(__name__)

__all__ = ["ANSWER_FILE", "DEFINITION", "GENERATED_QUERY_FILE", "DataQueryCategory", "DataQueryEntry", "result_sets_match"]

GENERATED_QUERY_FILE = "query.al"
ANSWER_FILE = "answer.json"


class DataQueryEntry(BaseDatasetEntry):
    """Dataset entry for the data-query category — answer a BC data question using the data tools.

    Execution-based: the agent retrieves the actual data (writing the rows to answer.json, plus the
    query it used to query.al); evaluation compares those rows to the entry's expected rows, computed
    on demand by running ``gold_query`` against the fixed Contoso container. The workspace is
    scaffolded by the category, so there is no repo or commit.
    """

    nl_prompt: Annotated[str, Field(min_length=1, pattern=r"^[^\x00]*$")]
    gold_query: Annotated[str, Field(min_length=1, pattern=r"^[^\x00]*$")]
    # Whether row order is significant when comparing result sets (e.g. the question asks for a
    # specific ranking). Defaults to False: result sets are compared order-insensitively.
    ordered: bool = False

    @property
    @override
    def customization_profile(self) -> str:
        return "dataquery"

    @override
    def get_task(self) -> str:
        return self.nl_prompt

    @override
    def get_expected_output(self) -> str:
        return self.gold_query


def _load_answer_rows(answer_file: Path) -> list[Mapping[str, object]]:
    """Parse the agent's answer.json into a list of row objects.

    Accepts a bare JSON array, a single object (one row), or an object wrapping the rows under a
    common key (``value``/``rows``/``data``/``results``) so a copied OData payload still works.
    """
    try:
        data = json.loads(answer_file.read_text(encoding="utf-8-sig") or "[]")
    except json.JSONDecodeError as e:
        raise ValueError(f"{ANSWER_FILE} is not valid JSON: {e}") from None

    if isinstance(data, dict):
        wrapped = next((data[k] for k in ("value", "rows", "data", "results") if isinstance(data.get(k), list)), None)
        data = wrapped if wrapped is not None else [data]

    if not isinstance(data, list):
        raise TypeError(f"{ANSWER_FILE} must be a JSON array of row objects")

    rows: list[Mapping[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            raise TypeError(f"{ANSWER_FILE} rows must be JSON objects, got {type(row).__name__}")
        rows.append(row)
    return rows


def _normalize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, Decimal)):
        # Only values that arrived as numeric JSON types are canonicalized: scale/trailing-zero-
        # insensitive (500 == 500.0) with full precision preserved (1.00001 != 1.00002) and no float
        # rounding (Decimal built from the value's string form). Both gold and generated rows come
        # through the same OData->JSON pipeline, so amounts are numbers on both sides.
        try:
            return str(Decimal(str(value)).normalize())
        except (InvalidOperation, ValueError):
            return str(value)
    # Strings (and anything else) are preserved verbatim apart from a whitespace trim. Business Central
    # Code/No. fields are JSON strings even when digit-only, so "001" must NOT collapse to "1" — coercing
    # them through Decimal would let a wrong result be scored as matching the gold.
    return str(value).strip()


def _normalize_rows(rows: Sequence[Mapping[str, object]], ordered: bool) -> list[tuple[str, ...]]:
    # Compare on values only: drop OData/system metadata keys ('@'-prefixed) and ignore column
    # names/order so a correct query still matches the gold even if it names columns differently.
    normalized = [tuple(sorted(_normalize_value(v) for k, v in row.items() if not k.startswith("@"))) for row in rows]
    return normalized if ordered else sorted(normalized)


def result_sets_match(generated: Sequence[Mapping[str, object]], gold: Sequence[Mapping[str, object]], ordered: bool = False) -> bool:
    """Compare two query result sets for equality.

    Values are compared (numbers normalized, column names/order ignored); row order is ignored
    unless ``ordered`` is True (the question asks for a specific ranking).
    """
    return _normalize_rows(generated, ordered) == _normalize_rows(gold, ordered)


class DataQueryCategory(Category[EvaluationContext[DataQueryEntry], ExecutionBasedEvaluationResult]):
    """Generate an AL query, evaluate deterministically.

    The agent answers a data question by retrieving the ACTUAL data with the BC data tools and writing
    the rows to ``answer.json`` (plus the ``query.al`` it used, kept only for inspection). Evaluation
    runs the entry's gold query against the container's fixed (Contoso) dataset and compares the gold
    rows to the agent's rows: build = the agent produced a well-formed answer.json; resolved = its rows
    match the gold query's. The data can't be answered from model knowledge, so a correct answer requires
    genuinely querying the environment.
    """

    @override
    def prepare_workspace(self, task: EvaluationContext[DataQueryEntry]) -> None:
        # The workspace is shared into the running container, so its contents are cleared in place.
        clear_directory(task.repo_path)

    @override
    def prepare(self, task: EvaluationContext[DataQueryEntry]) -> None:
        self.prepare_workspace(task)

    @override
    def grade(self, task: EvaluationContext[DataQueryEntry], result: AgentResult) -> ExecutionBasedEvaluationResult:
        query_file = task.repo_path / GENERATED_QUERY_FILE
        # query.al is only an inspection artifact now; scoring is on the data the agent retrieved.
        generated_query = query_file.read_text(encoding="utf-8").strip() if query_file.exists() else ""
        answer_file = task.repo_path / ANSWER_FILE

        # Gold rows come first and deliberately fail loudly (see _gold_rows): a gold query that can't
        # compile/run is a harness/dataset bug and must red the job. Everything below this line is the
        # AGENT's own outcome, recorded as build=False (not raised) so a model that fails the task shows
        # up honestly in the results/leaderboard instead of aborting the whole matrix job.
        gold_rows = self._gold_rows(task)

        if not answer_file.exists():
            # The agent finished without writing answer.json = it failed the task. This is a real,
            # measured benchmark outcome (build=False), not a hidden harness error, so we record it and
            # keep CI green rather than failing the job.
            logger.warning(f"Agent produced no {ANSWER_FILE} for {task.entry.instance_id}")
            return ExecutionBasedEvaluationResult.create_build_failure(task, result, output=generated_query, error_message=f"No {ANSWER_FILE} produced")

        try:
            agent_rows = _load_answer_rows(answer_file)
        except (ValueError, TypeError) as e:
            # Malformed answer.json is likewise the agent's failure, recorded as build=False.
            logger.warning(f"Unusable {ANSWER_FILE} for {task.entry.instance_id}: {e}")
            return ExecutionBasedEvaluationResult.create_build_failure(task, result, output=generated_query, error_message=str(e))

        resolved = result_sets_match(agent_rows, gold_rows, task.entry.ordered)
        error_message = None if resolved else f"Result set mismatch: answer {len(agent_rows)} rows vs gold {len(gold_rows)} rows"
        logger.info(f"{task.entry.instance_id}: build=True resolved={resolved}")
        return ExecutionBasedEvaluationResult.create_result(task, result, output=generated_query, build=True, resolved=resolved, error_message=error_message)

    def _gold_rows(self, context: EvaluationContext[DataQueryEntry]) -> Sequence[Mapping[str, object]]:
        """The expected rows: run the entry's gold query live against the container's fixed dataset.

        Computing the gold on demand keeps it resilient to demo-data changes (no stale baked rows). A
        gold query that doesn't compile/run — or that returns zero rows — is a harness/dataset bug, not
        the agent's fault, so this deliberately does NOT catch those failures: it must fail the run
        loudly. In particular an empty gold is rejected (see EmptyGoldResultError) so an agent that
        retrieved nothing cannot spuriously match it.
        """
        from bcbench.operations import execute_al_query

        logger.info(f"Running gold query live for {context.entry.instance_id}")
        company = context.get_container().company
        rows = execute_al_query(context.entry.gold_query, context.get_container(), context.entry.environment_setup_version, context.repo_path, "gold", company=company)
        if not rows:
            # An empty gold would make an empty agent answer spuriously "match" (result_sets_match([],
            # []) is True), scoring a run that retrieved nothing as resolved. Every question has a
            # non-empty answer, so treat this as a harness/environment failure and fail loudly.
            raise EmptyGoldResultError(context.entry.instance_id)
        return rows


DEFINITION: CategoryDefinition[DataQueryEntry] = CategoryDefinition(
    category=EvaluationCategory.DATA_QUERY,
    dataset_files={DatasetTier.GOLD: "dataquery.jsonl"},
    entry_type=DataQueryEntry,
    result_type=ExecutionBasedEvaluationResult,
    summary_type=ExecutionBasedEvaluationResultSummary,
    aggregate_type=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    judge=None,
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=False,
    make=lambda _agent_config: DataQueryCategory(),
)
