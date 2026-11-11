import importlib.util
import json
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
    return [SimpleNamespace(name=name, score=value, metadata={}) for name in ("test_passed", "critical_pass_rate", "pass_rate")]


def test_scores_every_row_and_preserves_failed_checklists(tmp_path):
    source = tmp_path / "input.jsonl"
    output = tmp_path / "scores.jsonl"
    rows = [{"input": "task", "output": str(i), "expected": [], "metadata": {"id": i}} for i in range(2)]
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
