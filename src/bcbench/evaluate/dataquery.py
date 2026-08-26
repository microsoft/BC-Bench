import json
import os
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bcbench.dataset import DataQueryEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import clear_directory
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["DataQueryPipeline", "result_sets_match"]

GENERATED_QUERY_FILE = "query.al"
ANSWER_FILE = "answer.json"


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


class DataQueryPipeline(EvaluationPipeline[DataQueryEntry]):
    """Pipeline for the data-query category — generate an AL query, evaluate deterministically.

    The agent answers a data question by retrieving the ACTUAL data with the BC data tools and writing
    the rows to ``answer.json`` (plus the ``query.al`` it used, kept only for inspection). Evaluation
    runs the entry's gold query against the container's fixed (Contoso) dataset and compares the gold
    rows to the agent's rows: build = the agent produced a well-formed answer.json; resolved = its rows
    match the gold query's. The data can't be answered from model knowledge, so a correct answer requires
    genuinely querying the environment.
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
        query_file = context.repo_path / GENERATED_QUERY_FILE
        # query.al is only an inspection artifact now; scoring is on the data the agent retrieved.
        generated_query = query_file.read_text(encoding="utf-8").strip() if query_file.exists() else ""
        answer_file = context.repo_path / ANSWER_FILE

        gold_rows = self._gold_rows(context)

        if not answer_file.exists():
            logger.warning(f"Agent produced no {ANSWER_FILE} for {context.entry.instance_id}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output=generated_query, error_message=f"No {ANSWER_FILE} produced"))
            return

        try:
            agent_rows = _load_answer_rows(answer_file)
        except (ValueError, TypeError) as e:
            logger.warning(f"Unusable {ANSWER_FILE} for {context.entry.instance_id}: {e}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output=generated_query, error_message=str(e)))
            return

        resolved = result_sets_match(agent_rows, gold_rows, context.entry.ordered)
        error_message = None if resolved else f"Result set mismatch: answer {len(agent_rows)} rows vs gold {len(gold_rows)} rows"
        result = ExecutionBasedEvaluationResult.create_result(context, output=generated_query, build=True, resolved=resolved, error_message=error_message)
        logger.info(f"{context.entry.instance_id}: build=True resolved={resolved}")
        self.save_result(context, result)

    def _gold_rows(self, context: EvaluationContext[DataQueryEntry]) -> Sequence[Mapping[str, object]]:
        """The expected rows: run the entry's gold query live against the container's fixed dataset.

        Computing the gold on demand keeps it resilient to demo-data changes (no stale baked rows). A
        gold query that doesn't compile/run is a harness/dataset bug, not the agent's fault, so this
        deliberately does NOT catch its failure — it must fail the run loudly.
        """
        from bcbench.operations import execute_al_query

        logger.info(f"Running gold query live for {context.entry.instance_id}")
        # Pin the gold query to the same company the agent queried via MCP (BC_MCP_COMPANY), so the
        # comparison is against the same data rather than an arbitrary first company.
        company = os.environ.get("BC_MCP_COMPANY")
        return execute_al_query(context.entry.gold_query, context.get_container(), context.entry.environment_setup_version, context.repo_path, "gold", company=company)
