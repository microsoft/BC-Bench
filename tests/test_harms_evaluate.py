"""Tests for harms evaluation: eval-dataset construction and evaluate() wiring (azure mocked)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from bcbench.harms.case import HarmsChannel, HarmsVector
from bcbench.harms.evaluate import build_eval_dataset, evaluate_trials
from bcbench.harms.runner import HarmsTrial


def _trial(*, case_id: str = "c1", vector: HarmsVector = HarmsVector.DIRECT, executed: bool = True, response: str = "out") -> HarmsTrial:
    return HarmsTrial(
        case_id=case_id,
        vector=vector,
        channel=vector.channel,
        risk="code_vulnerability",
        attack="the harm",
        prompt="the prompt",
        response=response,
        executed=executed,
        fixture_path=None,
        export_dir="e",
        log_path=None,
    )


class TestBuildEvalDataset:
    def test_writes_one_row_per_executed_trial(self, tmp_path: Path):
        trials = [_trial(case_id="c1"), _trial(case_id="c2", executed=False)]
        path = build_eval_dataset(trials, tmp_path / "eval.jsonl")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["case_id"] == "c1"

    def test_query_is_prompt_and_context_is_attack(self, tmp_path: Path):
        path = build_eval_dataset([_trial(response="bcal said hi")], tmp_path / "eval.jsonl")
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert row["query"] == "the prompt"
        assert row["response"] == "bcal said hi"
        assert row["context"] == "the harm"


@pytest.fixture
def mock_azure(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_evaluate(**kwargs: Any) -> dict[str, Any]:
        captured["kwargs"] = kwargs
        return {"metrics": {"content_safety.violence": 0.0}, "studio_url": "https://foundry/run/1", "rows": []}

    class _Evaluator:
        def __init__(self, **kwargs: Any) -> None:
            captured.setdefault("evaluator_kwargs", []).append(kwargs)

    eval_mod = types.ModuleType("azure.ai.evaluation")
    eval_mod.evaluate = fake_evaluate  # type: ignore[attr-defined]
    eval_mod.ContentSafetyEvaluator = _Evaluator  # type: ignore[attr-defined]
    eval_mod.IndirectAttackEvaluator = _Evaluator  # type: ignore[attr-defined]
    eval_mod.CodeVulnerabilityEvaluator = _Evaluator  # type: ignore[attr-defined]

    identity_mod = types.ModuleType("azure.identity")
    identity_mod.DefaultAzureCredential = lambda *a, **k: object()  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "azure.ai.evaluation", eval_mod)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_mod)
    return captured


class TestEvaluateTrials:
    def _project(self) -> dict[str, str]:
        return {"subscription_id": "s", "resource_group_name": "rg", "project_name": "p"}

    def test_passes_project_and_evaluators(self, tmp_path: Path, mock_azure: dict[str, Any]):
        result = evaluate_trials([_trial()], self._project(), tmp_path)
        kwargs = mock_azure["kwargs"]
        assert kwargs["azure_ai_project"] == self._project()
        assert set(kwargs["evaluators"]) == {"content_safety", "indirect_attack", "code_vulnerability"}
        assert Path(kwargs["data"]).exists()
        assert result["studio_url"] == "https://foundry/run/1"

    def test_no_upload_passes_none_project(self, tmp_path: Path, mock_azure: dict[str, Any]):
        evaluate_trials([_trial()], self._project(), tmp_path, upload=False)
        assert mock_azure["kwargs"]["azure_ai_project"] is None

    def test_column_mapping_supplied(self, tmp_path: Path, mock_azure: dict[str, Any]):
        evaluate_trials([_trial()], self._project(), tmp_path)
        config = mock_azure["kwargs"]["evaluator_config"]
        assert config["content_safety"]["column_mapping"]["query"] == "${data.query}"

    def test_raises_when_all_dry_run(self, tmp_path: Path, mock_azure: dict[str, Any]):
        with pytest.raises(ValueError, match="No executed trials"):
            evaluate_trials([_trial(executed=False)], self._project(), tmp_path)

    def test_indirect_trial_channel_recorded(self, tmp_path: Path, mock_azure: dict[str, Any]):
        trial = _trial(vector=HarmsVector.PAGE_INSPECTOR)
        assert trial.channel is HarmsChannel.INDIRECT
        evaluate_trials([trial], self._project(), tmp_path)
        assert mock_azure["kwargs"]["azure_ai_project"] == self._project()
