import argparse
from types import SimpleNamespace

import pytest

from bcbench import bceval_runner
from bcbench.bceval_runner import _dataset_is_complete, _kusto_source_id
from bcbench.retry import RetryPolicy


class _Results:
    def model_dump_json(self, **kwargs):
        return "{}"


def test_incomplete_dataset_blocks_external_storage():
    dataset = [
        SimpleNamespace(metadata={"evaluation_complete": False}),
        SimpleNamespace(metadata={"evaluation_complete": False}),
    ]

    assert _dataset_is_complete(dataset) is False


def test_complete_metadata_cannot_hide_missing_exported_rows():
    dataset = [
        SimpleNamespace(id="entry-a", metadata={"evaluation_complete": True, "expected_entry_count": 2}),
    ]

    assert _dataset_is_complete(dataset) is False


def test_kusto_source_id_is_stable_within_a_run_attempt():
    first = _kusto_source_id("123", "2", ["entry-b", "entry-a"])
    second = _kusto_source_id("123", "2", ["entry-a", "entry-b"])

    assert first == second


def test_kusto_source_id_changes_between_run_attempts():
    assert _kusto_source_id("123", "1", ["entry-a"]) != _kusto_source_id("123", "2", ["entry-a"])


def test_bceval_scoring_retries_http_529(monkeypatch):
    calls = 0

    class _Scorer:
        def __init__(self, **kwargs):
            pass

        def score(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("HTTP 529: all deployments temporarily unavailable / circuit breaker open")
            return SimpleNamespace(model_dump_json=lambda **_: "{}")

    monkeypatch.setattr(bceval_runner, "_SCORING_RETRY_POLICY", RetryPolicy(max_attempts=3, initial_delay_seconds=0, max_delay_seconds=0))
    monkeypatch.setattr(
        bceval_runner.importlib,
        "import_module",
        lambda name: SimpleNamespace(BraintrustScorer=_Scorer) if name.endswith("bc_braintrust_scorer") else None,
    )
    args = argparse.Namespace(
        eval_suite_name="nl2al",
        metadata="{}",
        feature_name="BC-Bench",
        source="sha",
        use_capi=True,
        run_id="123",
        eval_run_name="run",
        evaluators="judge",
        evaluator_definitions="scores.py",
        metric_definitions="metrics.py",
        metrics="metrics",
        tags="tag",
        core_score="score",
    )

    bceval_runner._score_dataset(args, [SimpleNamespace(metadata={})])

    assert calls == 3


def test_braintrust_upload_retries_transient_failure(monkeypatch):
    calls = 0

    class _Storage:
        def store(self, results):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("HTTP 503 Service Unavailable")

    monkeypatch.setattr(bceval_runner, "_STORAGE_RETRY_POLICY", RetryPolicy(max_attempts=3, initial_delay_seconds=0, max_delay_seconds=0))
    monkeypatch.setattr(
        bceval_runner.importlib,
        "import_module",
        lambda name: SimpleNamespace(BraintrustStorage=_Storage) if name.endswith("bc_braintrust_storage") else None,
    )

    bceval_runner._store_braintrust(_Results())

    assert calls == 3


def test_kusto_validation_and_upload_retry_together(monkeypatch):
    validation_calls = 0
    ingestion_calls = 0

    class _Storage:
        def validate_destination(self):
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls < 3:
                raise RuntimeError("HTTP 503 Service Unavailable")

        def to_kusto_rows(self, results):
            return [{"EvalResultId": "entry-a"}]

    class _Client:
        def __init__(self, builder):
            pass

        def ingest_from_stream(self, descriptor, *, ingestion_properties):
            nonlocal ingestion_calls
            ingestion_calls += 1

        def close(self):
            pass

    def get_credential():
        return object()

    modules = {
        "bc_eval.common": SimpleNamespace(
            KUSTO_EVAL_RESULTS_TABLE="AIEvalResults",
            custom_json_serializer=str,
            get_credential=get_credential,
        ),
        "bc_eval.storage.bc_kusto_storage": SimpleNamespace(KustoStorage=_Storage),
        "azure.kusto.data": SimpleNamespace(
            KustoConnectionStringBuilder=SimpleNamespace(
                with_azure_token_credential=lambda cluster, credential: object(),
            )
        ),
        "azure.kusto.ingest": SimpleNamespace(
            IngestionProperties=lambda **kwargs: object(),
            QueuedIngestClient=_Client,
        ),
        "azure.kusto.ingest.ingestion_properties": SimpleNamespace(DataFormat=SimpleNamespace(JSON="json")),
        "azure.kusto.ingest.descriptors": SimpleNamespace(StreamDescriptor=lambda stream, source_id: object()),
    }
    monkeypatch.setattr(bceval_runner, "_STORAGE_RETRY_POLICY", RetryPolicy(max_attempts=3, initial_delay_seconds=0, max_delay_seconds=0))
    monkeypatch.setattr(bceval_runner.importlib, "import_module", modules.__getitem__)
    monkeypatch.setenv("KUSTO_CLUSTER", "https://cluster.kusto.windows.net")
    monkeypatch.setenv("KUSTO_DATABASE", "database")

    bceval_runner._store_kusto(_Results(), "123", "1")

    assert validation_calls == 3
    assert ingestion_calls == 1


def test_calculate_attempts_all_storage_targets_before_failing(monkeypatch, tmp_path):
    stored = []
    dataset = [SimpleNamespace(id="entry-a", metadata={"evaluation_complete": True, "expected_entry_count": 1})]
    args = argparse.Namespace(
        input_file=tmp_path / "input.jsonl",
        output_file=tmp_path / "scored.json",
        storage=["braintrust", "kusto"],
        run_id="123",
        run_attempt="1",
    )

    monkeypatch.setattr(bceval_runner, "_load_bc_eval_environment", lambda: None)
    monkeypatch.setattr(bceval_runner, "_load_dataset", lambda input_file: dataset)
    monkeypatch.setattr(bceval_runner, "_score_dataset", lambda calculate_args, rows: _Results())
    monkeypatch.setattr(bceval_runner, "_write_scoring_results", lambda results, output_file: None)
    monkeypatch.setattr(
        bceval_runner,
        "_store_braintrust",
        lambda results: (_ for _ in ()).throw(RuntimeError("HTTP 503 Service Unavailable")),
    )
    monkeypatch.setattr(bceval_runner, "_store_kusto", lambda results, run_id, run_attempt: stored.append("kusto"))

    with pytest.raises(ExceptionGroup, match="storage targets failed"):
        bceval_runner.calculate(args)

    assert stored == ["kusto"]


def test_health_query_correlates_metadata_run_id(monkeypatch):
    queries = []
    common = SimpleNamespace(
        KUSTO_EVAL_RESULTS_TABLE="AIEvalResults",
        execute_kusto_query=lambda query: queries.append(query) or [{"produced_entry_count": 110}],
    )
    monkeypatch.setattr(bceval_runner.importlib, "import_module", lambda name: common)

    result = bceval_runner._query_health("37176640925")

    assert result["produced_entry_count"] == 110
    assert 'tostring(Metadata.run_id) == "37176640925"' in queries[0]
    assert 'EvalSuiteId == "nl2al"' in queries[0]
