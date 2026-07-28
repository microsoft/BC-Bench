import shutil
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bcbench.dataset import DataQueryEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, BuildTimeoutExpired
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
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
    text = str(value).strip()
    try:
        # Canonical decimal form: scale/trailing-zero-insensitive (500 == 500.0) but full precision
        # preserved, so distinct values like 1.00001 and 1.00002 are NOT collapsed. No float rounding.
        return str(Decimal(text).normalize())
    except (InvalidOperation, ValueError):
        return text


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


def _force_remove_readonly(func: Callable, path: str, _: object) -> None:
    Path(path).chmod(0o666)
    func(path)


def _prepare_repo_path(repo_path: Path) -> None:
    # Clear the workspace *contents* but not the directory itself: for data-query the workspace is
    # mounted into the running BC container (shared folder), so removing the top dir fails with
    # WinError 32 (in use). The workflow hands us a fresh empty dir; locally this clears stale files.
    repo_path.mkdir(parents=True, exist_ok=True)
    for child in repo_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child, onexc=_force_remove_readonly)
        else:
            child.chmod(0o666)
            child.unlink()


class DataQueryPipeline(EvaluationPipeline[DataQueryEntry]):
    """Pipeline for the data-query category — generate an AL query, evaluate deterministically.

    The agent writes an AL query to ``query.al``. Evaluation compiles + runs both the generated
    query and the entry's gold query against the container's fixed (Contoso) dataset and compares
    the result sets: build = the generated query compiled and ran; resolved = its result set
    matches the gold query's.
    """

    def setup_workspace(self, entry: DataQueryEntry, repo_path: Path) -> None:
        _prepare_repo_path(repo_path)

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

        try:
            generated_rows = execute_al_query(generated_query, container, version, context.repo_path, "generated")
        except (BuildError, BuildTimeoutExpired) as e:
            logger.exception(f"Generated query failed to compile/run for {context.entry.instance_id}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output=generated_query, error_message=str(e)))
            return

        # The gold query is authored to compile; a failure here is a harness/dataset problem, not the
        # agent's. Record it as unscorable so it is not counted against the agent's resolution rate.
        try:
            gold_rows = execute_al_query(context.entry.gold_query, container, version, context.repo_path, "gold")
        except (BuildError, BuildTimeoutExpired) as e:
            logger.exception(f"Gold query failed to compile/run for {context.entry.instance_id}")
            self.save_result(
                context,
                ExecutionBasedEvaluationResult.create_unscorable(context, output=generated_query, error_message=f"Gold query failed (harness/dataset issue, not the agent): {e}"),
            )
            return

        resolved = result_sets_match(generated_rows, gold_rows, context.entry.ordered)
        error_message = None if resolved else f"Result set mismatch: generated {len(generated_rows)} rows vs gold {len(gold_rows)} rows"
        result = ExecutionBasedEvaluationResult.create_result(context, output=generated_query, build=True, resolved=resolved, error_message=error_message)
        logger.info(f"{context.entry.instance_id}: build=True resolved={resolved}")
        self.save_result(context, result)
