import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("score_nl2al", Path(__file__).parents[1] / "tools" / "score_nl2al.py")
assert spec
assert spec.loader
score_nl2al = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_nl2al)


def scores(value=1):
    return [
        SimpleNamespace(name=name, score=value, metadata={"assertions": [{"text": "requirement", "pass": bool(value), "reasoning": "Observed evidence"}]})
        for name in ("test_passed", "critical_pass_rate", "pass_rate")
    ]


def test_scores_every_row_and_preserves_failed_checklists(tmp_path):
    source = tmp_path / "input.jsonl"
    output = tmp_path / "scores.jsonl"
    rows = [{"input": "task", "output": str(i), "expected": {"assertions": [{"text": "requirement", "level": "critical"}]}, "metadata": {"id": i}} for i in range(2)]
    source.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    judge = Mock()
    judge.eval.side_effect = [scores(), scores(0)]

    score_nl2al.score_export(source, output, judge, "judge-model")

    saved = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["metadata"]["id"] for row in saved] == [0, 1]
    assert saved[1]["scores"][0]["score"] == 0
    with pytest.raises(FileExistsError):
        score_nl2al.score_export(source, output, judge, "judge-model")


@pytest.mark.parametrize("result", [[], scores(float("nan")), [SimpleNamespace(name="test_passed", score=1, metadata={})], scores(None)])
def test_incomplete_judging_fails_and_preserves_raw_result(tmp_path, result):
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"input": "", "output": "", "expected": [], "metadata": {}}))
    output = tmp_path / "scores.jsonl"
    judge = Mock()
    judge.eval.return_value = result

    with pytest.raises(RuntimeError, match="Incomplete accuracy judging"):
        score_nl2al.score_export(source, output, judge, "judge-model")

    assert output.exists()
    assert len(output.read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "verdicts",
    [
        [],
        [{"text": "requirement", "pass": "false", "reasoning": "no"}],
        [{"text": "requirement", "pass": 0, "reasoning": "no"}],
        [{"text": "requirement", "pass": False, "reasoning": "No evaluation returned"}],
        [{"text": "unknown", "pass": True, "reasoning": "yes"}],
    ],
)
def test_rejects_incomplete_or_coerced_raw_verdicts(verdicts):
    with pytest.raises(ValueError, match=r"verdict|Boolean|reasoning|assertion"):
        score_nl2al.validate_assertion_verdicts(verdicts, [{"text": "requirement", "level": "critical"}])


def test_rejects_duplicate_raw_verdicts():
    verdict = {"text": "first", "pass": True, "reasoning": "Observed"}
    with pytest.raises(ValueError, match="duplicate"):
        score_nl2al.validate_assertion_verdicts([verdict, verdict], [{"text": "first"}, {"text": "second"}])


def test_raw_parser_failure_is_preserved_without_scores(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"input": "task", "output": "code", "expected": {}, "metadata": {}}))
    raw = {"choices": [{"message": {"content": '{"assertions":[]}'}}]}
    judge = Mock()
    judge.eval.side_effect = score_nl2al.ChecklistResponseError(raw, "Missing verdict")
    output = tmp_path / "scores.jsonl"
    with pytest.raises(RuntimeError, match="raw judgment retained"):
        score_nl2al.score_export(source, output, judge, "judge")
    saved = json.loads(output.read_text())
    assert saved["raw_judge_response"] == raw
    assert saved["scores"] == []


@pytest.mark.parametrize("passed", ["false", False])
def test_owned_adapter_validates_before_upstream_parser(monkeypatch, passed):
    downstream = Mock(return_value=[])

    class Upstream:
        def __init__(self, *, client):
            pass

        _process_response = downstream

    monkeypatch.setitem(sys.modules, "bc_eval.scorers.autoeval.lmchecklist", SimpleNamespace(LmChecklist=Upstream))
    judge = score_nl2al.create_checklist_judge(Mock())
    raw = {"choices": [{"message": {"content": json.dumps({"assertions": [{"text": "requirement", "pass": passed, "reasoning": "Observed"}]})}}]}
    if isinstance(passed, bool):
        judge._process_response(raw, [{"text": "requirement"}])
        downstream.assert_called_once()
    else:
        with pytest.raises(score_nl2al.ChecklistResponseError, match="Boolean") as failure:
            judge._process_response(raw, [{"text": "requirement"}])
        assert failure.value.response == raw
        downstream.assert_not_called()
