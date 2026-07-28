import contextlib
import json
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
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


@contextlib.contextmanager
def _withhold_gold_from_agent(dataset_path: Path) -> Iterator[None]:
    """Strip ``gold_query`` from the on-disk dataset while the agent generates its answer.

    The agent runs with unrestricted filesystem tools in a workspace under the checkout, so it could
    otherwise read the reference answers straight out of ``dataset/dataquery.jsonl`` and copy them,
    invalidating the benchmark. The harness already loads this entry (with its gold) into memory
    before the agent starts, so scoring is unaffected. The original file is restored on exit.
    """
    if not dataset_path.exists():
        yield
        return
    original = dataset_path.read_text(encoding="utf-8")
    try:
        stripped: list[str] = []
        for line in original.splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            obj.pop("gold_query", None)
            stripped.append(json.dumps(obj, ensure_ascii=False))
        dataset_path.write_text("\n".join(stripped) + "\n", encoding="utf-8")
        yield
    finally:
        dataset_path.write_text(original, encoding="utf-8")


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
        # The agent runs with unrestricted filesystem tools in a workspace under the checkout, so it could
        # otherwise read the reference answers from the dataset. Withhold the gold queries from disk during
        # generation; the harness already holds this entry's gold in memory for scoring.
        with (
            github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"),
            _withhold_gold_from_agent(context.category.dataset_path),
        ):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[DataQueryEntry]) -> None:
        from bcbench.operations import execute_al_query

        query_file = context.repo_path / GENERATED_QUERY_FILE
        generated_query = query_file.read_text(encoding="utf-8").strip() if query_file.exists() else ""

        container = context.get_container()
        version = context.entry.environment_setup_version

        # Establish gold validity FIRST, independent of the agent's output: a broken gold (a
        # harness/dataset problem) must be recorded as unscorable regardless of whether the agent's
        # query compiled — otherwise, when the agent query also fails, the broken entry is silently
        # counted against that agent.
        try:
            gold_rows = execute_al_query(context.entry.gold_query, container, version, context.repo_path, "gold")
        except (BuildError, BuildTimeoutExpired) as e:
            logger.exception(f"Gold query failed to compile/run for {context.entry.instance_id}")
            self.save_result(
                context,
                ExecutionBasedEvaluationResult.create_unscorable(context, output=generated_query, error_message=f"Gold query failed (harness/dataset issue, not the agent): {e}"),
            )
            return

        if not generated_query:
            logger.warning(f"Agent produced no {GENERATED_QUERY_FILE} for {context.entry.instance_id}")
            self.save_result(context, ExecutionBasedEvaluationResult.create_build_failure(context, output="", error_message=f"No {GENERATED_QUERY_FILE} produced"))
            return

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
