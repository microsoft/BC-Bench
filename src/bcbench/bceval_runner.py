from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from bcbench.retry import RetryPolicy, is_transient_dependency_failure, retry_transient

_SCORING_RETRY_POLICY = RetryPolicy(max_attempts=3, initial_delay_seconds=30, max_delay_seconds=120)
_STORAGE_RETRY_POLICY = RetryPolicy(max_attempts=3, initial_delay_seconds=15, max_delay_seconds=60)


class _EvalLine(Protocol):
    id: str
    metadata: dict[str, object]


class _ScoringResults(Protocol):
    def model_dump_json(self, *, indent: int) -> str: ...


def _load_bc_eval_environment() -> None:
    bc_eval = importlib.import_module("bc_eval")
    dotenv = importlib.import_module("dotenv")
    if bc_eval.__file__ is None:
        raise RuntimeError("bc_eval package path is unavailable.")
    package_dir = Path(bc_eval.__file__).parent
    dotenv.load_dotenv(package_dir / ".env.default", override=False)
    dotenv.load_dotenv(override=True)


def _load_dataset(input_file: Path) -> list[_EvalLine]:
    common = importlib.import_module("bc_eval.common")
    with input_file.open(encoding="utf-8") as stream:
        return cast(list[_EvalLine], [common.EvalLine.model_validate_json(line) for line in stream if line.strip()])


def _dataset_is_complete(dataset: Sequence[_EvalLine]) -> bool:
    completeness_values = {row.metadata["evaluation_complete"] for row in dataset if "evaluation_complete" in row.metadata}
    if not completeness_values:
        return True
    if len(completeness_values) != 1:
        raise ValueError("Input rows contain inconsistent evaluation_complete metadata.")
    if completeness_values.pop() is not True:
        return False

    expected_counts = {row.metadata["expected_entry_count"] for row in dataset if "expected_entry_count" in row.metadata}
    if not expected_counts:
        return True
    if len(expected_counts) != 1:
        raise ValueError("Input rows contain inconsistent expected_entry_count metadata.")

    expected_count = expected_counts.pop()
    return isinstance(expected_count, int) and len(dataset) == expected_count and len({row.id for row in dataset}) == expected_count


def _score_dataset(args: argparse.Namespace, dataset: list[_EvalLine]) -> _ScoringResults:
    scorer_module = importlib.import_module("bc_eval.scorers.bc_braintrust_scorer")
    eval_suite_id = re.sub(r"[^a-z0-9]+", "-", args.eval_suite_name.lower()).strip("-")
    metadata = json.loads(args.metadata)
    metadata.update(
        {
            "FeatureName": args.feature_name,
            "EvalSuiteId": eval_suite_id,
            "Source": args.source,
        }
    )

    def score() -> _ScoringResults:
        scorer = scorer_module.BraintrustScorer(use_capi=args.use_capi)
        return cast(
            _ScoringResults,
            scorer.score(
                dataset,
                eval_id=args.run_id,
                eval_name=args.eval_suite_name,
                eval_run_name=args.eval_run_name,
                evaluators=_split_csv(args.evaluators),
                evaluator_definitions=args.evaluator_definitions,
                metric_definitions=args.metric_definitions,
                metrics=_split_csv(args.metrics),
                tags=_split_csv(args.tags),
                metadata=metadata,
                core_score=args.core_score,
                feature_name=args.feature_name,
                eval_suite_id=eval_suite_id,
                source=args.source,
            ),
        )

    return retry_transient(
        score,
        policy=_SCORING_RETRY_POLICY,
        on_retry=lambda error, attempt, delay: _log_retry("bceval scoring", error, attempt, delay),
    )


def _store_braintrust(results: _ScoringResults) -> None:
    storage_module = importlib.import_module("bc_eval.storage.bc_braintrust_storage")

    def store() -> None:
        # The experiment name contains the GitHub run ID and each row uses the stable instance ID,
        # so replaying a transiently failed flush updates the same experiment rows.
        storage_module.BraintrustStorage().store(results)

    retry_transient(
        store,
        policy=_STORAGE_RETRY_POLICY,
        on_retry=lambda error, attempt, delay: _log_retry("Braintrust upload", error, attempt, delay),
    )


def _store_kusto(results: _ScoringResults, run_id: str, run_attempt: str) -> None:
    common = importlib.import_module("bc_eval.common")
    storage_module = importlib.import_module("bc_eval.storage.bc_kusto_storage")
    kusto_data = importlib.import_module("azure.kusto.data")
    kusto_ingest = importlib.import_module("azure.kusto.ingest")
    ingestion_properties = importlib.import_module("azure.kusto.ingest.ingestion_properties")
    descriptors = importlib.import_module("azure.kusto.ingest.descriptors")

    storage = storage_module.KustoStorage()
    rows = storage.to_kusto_rows(results)
    source_id = _kusto_source_id(run_id, run_attempt, [row["EvalResultId"] for row in rows])

    def store() -> None:
        storage.validate_destination()
        cluster = os.environ["KUSTO_CLUSTER"]
        database = os.environ["KUSTO_DATABASE"]
        builder = kusto_data.KustoConnectionStringBuilder.with_azure_token_credential(cluster, common.get_credential())
        client = kusto_ingest.QueuedIngestClient(builder)
        properties = kusto_ingest.IngestionProperties(
            database=database,
            table=common.KUSTO_EVAL_RESULTS_TABLE,
            data_format=ingestion_properties.DataFormat.JSON,
            flush_immediately=True,
        )
        payload = "\n".join(json.dumps(row, default=common.custom_json_serializer) for row in rows)
        descriptor = descriptors.StreamDescriptor(io.StringIO(payload), source_id=source_id)
        try:
            client.ingest_from_stream(descriptor, ingestion_properties=properties)
        finally:
            client.close()
        sys.stdout.write(f"Submitted {len(rows)} rows to Kusto with idempotent source ID {source_id}.\n")

    retry_transient(
        store,
        policy=_STORAGE_RETRY_POLICY,
        on_retry=lambda error, attempt, delay: _log_retry("Kusto upload", error, attempt, delay),
    )


def _kusto_source_id(run_id: str, run_attempt: str, result_ids: Sequence[str]) -> UUID:
    digest = hashlib.sha256("\n".join(sorted(result_ids)).encode()).hexdigest()
    return uuid5(NAMESPACE_URL, f"bcbench:{run_id}:{run_attempt}:{digest}")


def _write_scoring_results(results: _ScoringResults, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(results.model_dump_json(indent=2), encoding="utf-8")


def calculate(args: argparse.Namespace) -> int:
    _load_bc_eval_environment()
    dataset = _load_dataset(args.input_file)
    if not dataset:
        raise ValueError(f"No bceval rows found in {args.input_file}.")

    results = _score_dataset(args, dataset)
    _write_scoring_results(results, args.output_file)

    if not _dataset_is_complete(dataset):
        sys.stdout.write("::warning::Evaluation is incomplete; scored diagnostics were saved, but external storage was skipped.\n")
        return 0

    storage_operations: dict[str, Callable[[], None]] = {
        "braintrust": lambda: _store_braintrust(results),
        "kusto": lambda: _store_kusto(results, args.run_id, args.run_attempt),
    }
    storage_errors: list[Exception] = []
    for storage in args.storage:
        operation = storage_operations.get(storage)
        if operation is None:
            raise ValueError(f"Unsupported storage target: {storage}")
        try:
            operation()
        except Exception as error:  # noqa: BLE001 - independent storage targets must all be attempted before failing
            storage_errors.append(error)

    if storage_errors:
        raise ExceptionGroup("One or more bceval storage targets failed.", storage_errors)
    return 0


def _query_health(run_id: str) -> dict[str, Any]:
    common = importlib.import_module("bc_eval.common")
    query = f"""
{common.KUSTO_EVAL_RESULTS_TABLE}
| where tostring(Metadata.run_id) == {_kusto_string(run_id)}
| where EvalSuiteId == "nl2al" or EvalSuiteName == "nl2al"
| summarize
    produced_entry_count=dcount(EvalResultId),
    stored_row_count=count(),
    complete_row_count=countif(tobool(Metadata.evaluation_complete)),
    latest_ingestion_time=max(ingestion_time())
"""
    rows = common.execute_kusto_query(query)
    if not rows:
        return {
            "produced_entry_count": 0,
            "stored_row_count": 0,
            "complete_row_count": 0,
            "latest_ingestion_time": None,
        }
    return rows[0]


def health_check(args: argparse.Namespace) -> int:
    _load_bc_eval_environment()
    policy = RetryPolicy(max_attempts=args.max_attempts, initial_delay_seconds=args.initial_delay_seconds, max_delay_seconds=args.max_delay_seconds)
    latest: dict[str, Any] = {}

    for attempt in range(1, policy.max_attempts + 1):
        try:
            latest = _query_health(args.run_id)
        except Exception as error:
            if attempt == policy.max_attempts or not is_transient_dependency_failure(error):
                raise
            delay = policy.delay_after(attempt)
            _log_retry("Kusto health query", error, attempt, delay)
            time.sleep(delay)
            continue

        produced = int(latest.get("produced_entry_count") or 0)
        if produced >= args.expected_total:
            _write_health_summary(args, latest, healthy=True)
            return 0
        if attempt < policy.max_attempts:
            delay = policy.delay_after(attempt)
            sys.stdout.write(f"Kusto contains {produced}/{args.expected_total} distinct entries; checking again in {delay:g}s.\n")
            time.sleep(delay)

    _write_health_summary(args, latest, healthy=False)
    produced = int(latest.get("produced_entry_count") or 0)
    sys.stdout.write(f"::error title=Scheduled BCal ingestion incomplete::Run {args.run_id} has {produced}/{args.expected_total} distinct nl2al entries in Kusto.\n")
    return 1


def _write_health_summary(args: argparse.Namespace, result: dict[str, Any], *, healthy: bool) -> None:
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    status = ":white_check_mark: Healthy" if healthy else ":x: Missing or incomplete"
    run_label = f"[{args.run_id}]({args.run_url})" if args.run_url else args.run_id
    lines = [
        "## Scheduled BCal ingestion health",
        "",
        "| Run ID | Expected entries | Kusto distinct entries | Stored rows | Complete rows | Latest ingestion timestamp | Status |",
        "|:---|---:|---:|---:|---:|:---|:---|",
        (
            f"| {run_label} | {args.expected_total} | {int(result.get('produced_entry_count') or 0)} "
            f"| {int(result.get('stored_row_count') or 0)} | {int(result.get('complete_row_count') or 0)} "
            f"| {result.get('latest_ingestion_time') or 'N/A'} | {status} |"
        ),
        "",
        "_The timestamp above is the Kusto ingestion timestamp, not the evaluation execution date._",
    ]
    with Path(summary_file).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _kusto_string(value: str) -> str:
    return json.dumps(value)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _log_retry(operation: str, error: BaseException, attempt: int, delay: float) -> None:
    sys.stderr.write(
        f"::warning::{operation} attempt {attempt} failed with a transient dependency error: {error}. Retrying in {delay:g}s.",
    )
    sys.stderr.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    calculate_parser = subparsers.add_parser("calculate")
    calculate_parser.add_argument("--input-file", type=Path, required=True)
    calculate_parser.add_argument("--output-file", type=Path, required=True)
    calculate_parser.add_argument("--run-id", required=True)
    calculate_parser.add_argument("--run-attempt", required=True)
    calculate_parser.add_argument("--feature-name", required=True)
    calculate_parser.add_argument("--eval-suite-name", required=True)
    calculate_parser.add_argument("--eval-run-name", required=True)
    calculate_parser.add_argument("--tags", default="")
    calculate_parser.add_argument("--source", required=True)
    calculate_parser.add_argument("--evaluator-definitions", required=True)
    calculate_parser.add_argument("--evaluators", required=True)
    calculate_parser.add_argument("--core-score", required=True)
    calculate_parser.add_argument("--metric-definitions", required=True)
    calculate_parser.add_argument("--metrics", required=True)
    calculate_parser.add_argument("--metadata", default="{}")
    calculate_parser.add_argument("--use-capi", action="store_true")
    calculate_parser.add_argument("--storage", action="append", default=[], choices=("braintrust", "kusto"))
    calculate_parser.set_defaults(handler=calculate)

    health_parser = subparsers.add_parser("health-check")
    health_parser.add_argument("--run-id", required=True)
    health_parser.add_argument("--run-url", default="")
    health_parser.add_argument("--expected-total", type=int, required=True)
    health_parser.add_argument("--max-attempts", type=int, default=5)
    health_parser.add_argument("--initial-delay-seconds", type=float, default=15)
    health_parser.add_argument("--max-delay-seconds", type=float, default=60)
    health_parser.set_defaults(handler=health_check)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
