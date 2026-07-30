from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bcbench.dataset import DataQueryEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, BuildTimeoutExpired
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import clear_directory
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["DataQueryPipeline", "result_sets_match"]

GENERATED_QUERY_FILE = "query.al"


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


class DataQueryPipeline(EvaluationPipeline[DataQueryEntry]):
    """Pipeline for the data-query category — generate an AL query, evaluate deterministically.

    The agent writes an AL query to ``query.al``. Evaluation compiles + runs both the generated
    query and the entry's gold query against the container's fixed (Contoso) dataset and compares
    the result sets: build = the generated query compiled and ran; resolved = its result set
    matches the gold query's.
    """

    def setup_workspace(self, entry: DataQueryEntry, repo_path: Path) -> None:
        # The workspace is shared into the running container, so its contents are cleared in place.
        clear_directory(repo_path)

    def setup(self, context: EvaluationContext[DataQueryEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[DataQueryEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[DataQueryEntry]) -> None:
        from bcbench.operations import execute_al_query

        query_file = context.repo_path / GENERATED_QUERY_FILE
        generated_query = query_file.read_text(encoding="utf-8").strip() if query_file.exists() else ""

        if not generated_query:
            logger.warning(f"Agent produced no {GENERATED_QUERY_FILE} for {context.entry.instance_id}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output="", error_message=f"No {GENERATED_QUERY_FILE} produced"))
            return

        container = context.get_container()
        version = context.entry.environment_setup_version

        # Validate the gold query first, and deliberately do NOT catch its failure: a gold that doesn't
        # compile/run is a harness or dataset bug, not the agent's fault, so it must fail the run loudly
        # and get fixed rather than being silently scored or excluded.
        gold_rows = execute_al_query(context.entry.gold_query, container, version, context.repo_path, "gold")

        try:
            generated_rows = execute_al_query(generated_query, container, version, context.repo_path, "generated")
        except (BuildError, BuildTimeoutExpired) as e:
            logger.exception(f"Generated query failed to compile/run for {context.entry.instance_id}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output=generated_query, error_message=str(e)))
            return

        resolved = result_sets_match(generated_rows, gold_rows, context.entry.ordered)
        error_message = None if resolved else f"Result set mismatch: generated {len(generated_rows)} rows vs gold {len(gold_rows)} rows"
        result = ExecutionBasedEvaluationResult.create_result(context, output=generated_query, build=True, resolved=resolved, error_message=error_message)
        logger.info(f"{context.entry.instance_id}: build=True resolved={resolved}")
        self.save_result(context, result)
