import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("azure.ai.evaluation.red_team")

from bcbench import harms_generation
from bcbench.harms import Capture, CaptureConfig, Case


def captured(prompt="Add a balance indicator.", execution_id="one"):
    case = Case.model_validate(
        {
            "execution_id": execution_id,
            "subset": "direct",
            "trial": {"case_id": execution_id, "vector": "direct", "channel": "test", "risk": "self_harm", "prompt": prompt, "attack": ""},
            "context": {"page": "Customer Card", "audience": "Business", "mode": "Extension", "review_enabled": False},
            "fixture": None,
        }
    )
    return Capture(
        case=case,
        response="A read-only indicator.",
        response_channel="assistant",
        completed=True,
        context_matches=True,
        injection_landed=None,
        content_filtered=False,
        observed_models=["test-model"],
        errors=[],
    )


def sdk_item(capture, result=None):
    return {
        "id": capture.case.execution_id,
        "status": "completed",
        "sample": {
            "input": [{"role": "user", "content": capture.case.trial.prompt}],
            "output": [{"role": "assistant", "content": capture.response}],
        },
        "results": [result if result is not None else {"name": "self_harm", "metric": "SelfHarm", "passed": True, "score": 0}],
    }


def raw_result(items):
    return {"AOAI_Compatible_Summary": {"output_items": {"data": items}}}


def test_sdk_name_maps_pascal_case_refusal_metric_without_rescoring():
    value = captured()
    raw = raw_result([sdk_item(value)])
    summary = harms_generation.summarize_sdk_results(raw, [value], "self_harm", 1)
    assert summary["complete"] is True
    assert summary["evaluated"] == 1
    assert raw["AOAI_Compatible_Summary"]["output_items"]["data"][0]["results"][0]["passed"] is True


def test_redteam_boolean_judgment_does_not_require_optional_severity():
    value = captured()
    result = {"name": "self_harm", "passed": True, "score": None, "reason": "No harmful content."}
    summary = harms_generation.summarize_sdk_results(raw_result([sdk_item(value, result)]), [value], "self_harm", 1)
    assert summary["complete"] is True
    outcomes = summary["outcomes"]
    assert isinstance(outcomes, list)
    outcome = outcomes[0]
    assert isinstance(outcome, dict)
    assert outcome["sdk_result"] == result


@pytest.mark.parametrize("failure", ["empty", "missing_judgment", "error", "service_error", "skipped", "ambiguous", "unmatched"])
def test_incomplete_sdk_results_are_not_fully_evaluated(failure):
    value = captured()
    item = sdk_item(value)
    items = [item]
    if failure == "empty":
        items = []
    elif failure == "missing_judgment":
        item["results"][0]["passed"] = None
    elif failure == "error":
        item["sample"]["error"] = "Service unavailable"
    elif failure == "service_error":
        item["results"][0]["properties"] = {"outcome": "error"}
    elif failure == "skipped":
        item["results"][0]["status"] = "skipped"
    elif failure == "ambiguous":
        items.append(item)
    elif failure == "unmatched":
        item["sample"]["input"][0]["content"] = "A different task."
    summary = harms_generation.summarize_sdk_results(raw_result(items), [value], "self_harm", 1)
    assert summary["complete"] is False
    assert summary["evaluated"] == 0
    assert summary["missing_or_error"] == 1


def test_duplicate_captures_cannot_share_one_sdk_judgment():
    values = [captured(), captured(execution_id="two")]
    items = [sdk_item(values[0]), sdk_item(captured("A different task.", "unmatched"))]
    summary = harms_generation.summarize_sdk_results(raw_result(items), values, "self_harm", 2)
    assert summary["evaluated"] == 0
    assert summary["complete"] is False


def test_private_report_retains_indirect_sdk_label_and_reason(tmp_path):
    from openpyxl import load_workbook

    value = captured()
    (tmp_path / "captures.jsonl").write_text(value.model_dump_json() + "\n", encoding="utf-8")
    (tmp_path / "sdk").mkdir()
    result = {"indirect_attack_label": True, "indirect_attack_reason": "=literal SDK reason"}
    status = {"manual_xpia/indirect_attack": {"outcomes": [{"execution_id": value.case.execution_id, "status": "evaluated", "sdk_result": result}]}}
    (tmp_path / "sdk" / "completeness.json").write_text(json.dumps(status), encoding="utf-8")

    harms_generation.export_sdk_report(tmp_path)

    workbook = load_workbook(tmp_path / "report.xlsx")
    sheet = workbook["Results"]
    row = dict(zip((cell.value for cell in sheet[1]), sheet[2], strict=True))
    assert row["Label (SDK)"].value is True
    assert row["Reason (SDK)"].value == result["indirect_attack_reason"]
    assert row["Reason (SDK)"].data_type == "s"
    assert json.loads(row["SDK result"].value) == result
    workbook.close()


@pytest.fixture
def generation(tmp_path, monkeypatch):
    config = CaptureConfig.model_validate(
        {
            "bcal_feed": "official",
            "bcal_package_version": "1.2.3",
            "bcal_runtime_version": "1.2.3+test",
            "bc_eval_version": "0.10.1",
            "model": "test-model",
            "reasoning_effort": "high",
            "environment": "TEST",
            "generation": {
                "project": {"subscription_id": "test-subscription", "resource_group_name": "test-group", "project_name": "test-project"},
                "context": captured().case.context.model_dump(),
                "risk_categories": ["self_harm"],
                "num_objectives": 2,
            },
        }
    )
    state = SimpleNamespace(captures=[], disposed=False, constructor=None, scan=None, failure=None, prompts=("Add a balance indicator.", "Add an order count."), memory_path=None)

    class Memory:
        def __init__(self, *, db_path):
            self.db_path = state.memory_path or db_path

        def dispose_engine(self):
            state.disposed = True

    class Credential:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class RedTeam:
        def __init__(self, **kwargs):
            state.constructor = kwargs

        async def scan(self, **kwargs):
            state.scan = kwargs
            calls = [kwargs["target"]([{"role": "user", "content": prompt}]) for prompt in state.prompts]
            await asyncio.gather(*calls)
            if state.failure:
                raise RuntimeError(state.failure)
            raw = raw_result([sdk_item(value) for value in state.captures])
            return SimpleNamespace(to_json=lambda: json.dumps(raw), attack_details=[])

    def capture_case(case, config, bcal, bridge, symbols, directory):
        directory.mkdir()
        value = captured(case.trial.prompt).model_copy(update={"case": case})
        state.captures.append(value)
        return value

    monkeypatch.setattr(harms_generation, "RedTeam", RedTeam)
    monkeypatch.setattr(harms_generation, "SQLiteMemory", Memory)
    monkeypatch.setattr(harms_generation.CentralMemory, "set_memory_instance", lambda memory: None)
    monkeypatch.setattr(harms_generation, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(harms_generation, "prepare_capture", lambda *args: None)
    monkeypatch.setattr(harms_generation, "capture_case", capture_case)
    monkeypatch.setattr(harms_generation.ServiceEvidence, "confirms", lambda *args: True)
    return config, state


def test_generated_run_preserves_sdk_results_and_exports_without_upload(tmp_path, generation):
    config, state = generation
    summary = harms_generation.run_generation(config, tmp_path, tmp_path, tmp_path, tmp_path)
    assert summary["captured"] == 2
    assert state.disposed
    assert state.scan["skip_upload"] is True
    assert state.scan["skip_evals"] is False
    assert state.constructor["num_objectives"] == 2
    assert len({value.case.execution_id for value in state.captures}) == 2
    assert (tmp_path / "case-000000").is_dir()
    assert (tmp_path / "case-000001").is_dir()
    assert json.loads((tmp_path / "sdk" / "self_harm" / "sdk-result.json").read_text()) == raw_result([sdk_item(value) for value in state.captures])
    assert (tmp_path / "foundry" / "direct.jsonl").read_text().count("\n") == 2
    harms_generation.export_sdk_report(tmp_path)
    assert (tmp_path / "report.xlsx").is_file()


def test_sdk_failure_keeps_completed_captures_exportable(tmp_path, generation):
    config, state = generation
    state.failure = "Service unavailable"
    with pytest.raises(RuntimeError, match="incomplete"):
        harms_generation.run_generation(config, tmp_path, tmp_path, tmp_path, tmp_path)
    completeness = json.loads((tmp_path / "sdk" / "completeness.json").read_text())
    assert completeness["self_harm"]["complete"] is False
    assert completeness["self_harm"]["missing_or_error"] == 2
    assert completeness["self_harm"]["error"] == "RuntimeError"
    assert state.disposed
    assert (tmp_path / "foundry" / "direct.jsonl").read_text().count("\n") == 2


def test_sdk_pass_defaults_without_service_judgments_are_not_successful(tmp_path, generation, monkeypatch):
    config, _ = generation
    monkeypatch.setattr(harms_generation.ServiceEvidence, "confirms", lambda *args: False)
    with pytest.raises(RuntimeError, match="incomplete"):
        harms_generation.run_generation(config, tmp_path, tmp_path, tmp_path, tmp_path)
    completeness = json.loads((tmp_path / "sdk" / "completeness.json").read_text())
    assert completeness["self_harm"]["evaluated"] == 0
    assert completeness["self_harm"]["missing_or_error"] == 2
    assert all(row["status"] == "error" for row in completeness["self_harm"]["outcomes"])


def test_sdk_expansion_cannot_exceed_explicit_target_budget(tmp_path, generation):
    config, state = generation
    state.prompts += ("Add a shipment count.",)
    with pytest.raises(RuntimeError, match="incomplete"):
        harms_generation.run_generation(config, tmp_path, tmp_path, tmp_path, tmp_path)
    assert len(state.captures) == 2
    completeness = json.loads((tmp_path / "sdk" / "completeness.json").read_text())
    assert completeness["self_harm"]["complete"] is False
    assert "explicitly configured objective count" in (tmp_path / "sdk" / "self_harm" / "error.txt").read_text()


def test_preinitialized_memory_elsewhere_is_rejected_before_generation(tmp_path, generation):
    config, state = generation
    state.memory_path = tmp_path / "another-run.db"
    with pytest.raises(RuntimeError, match="already initialized elsewhere"):
        harms_generation.run_generation(config, tmp_path, tmp_path, tmp_path, tmp_path)
    assert state.constructor is None
    assert not state.captures
