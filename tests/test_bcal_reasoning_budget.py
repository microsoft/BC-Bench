import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
budget = importlib.import_module("bcal_reasoning_budget")


def create(tmp_path):
    return budget.StudyBudget.create(tmp_path / "study.db", [f"cell-{i}" for i in range(330)], "frozen")


def test_cell_admission_and_budget_cannot_be_reset_after_failure(tmp_path):
    study = create(tmp_path)
    with pytest.raises(budget.AdmissionError):
        study.reserve("cell-0", "main")
    study.admit("cell-0", "frozen")
    study.reserve("cell-0", "main")
    restored = budget.StudyBudget(study.path)
    assert restored.snapshot()["codingAttempts"] == 1
    with pytest.raises(budget.AdmissionError):
        restored.admit("cell-0", "frozen")
    with pytest.raises(FileExistsError):
        create(tmp_path)
    with pytest.raises(budget.AdmissionError):
        restored.admit("cell-1", "other-source")
    restored.stop()
    with pytest.raises(budget.AdmissionError):
        restored.reserve("cell-0", "main")
    assert restored.snapshot()["codingAttempts"] == 1


def test_actual_attempt_reservations_serialize_concurrent_main_and_judge_caps(tmp_path):
    study = create(tmp_path)
    study.admit("cell-0", "frozen")

    def reserve(role):
        try:
            study.reserve("cell-0", role)
        except budget.AdmissionError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(reserve, ["main"] * 90)) == 64
        assert sum(pool.map(reserve, ["judge"] * 12)) == 1
    receipt = study.snapshot()
    assert receipt["attempts"] == 65
    assert receipt["codingAttempts"] == 64
    assert receipt["judgeAttempts"] == 1
    with pytest.raises(budget.AdmissionError):
        study.reserve("cell-0", "auxiliary")


def test_innermost_transport_reserves_study_budget_before_any_actual_send(tmp_path):
    from types import SimpleNamespace

    coding = importlib.import_module("bcal_reasoning_coding")
    study = create(tmp_path)
    study.admit("cell-0", "frozen")
    local = coding.ProviderBudget(tmp_path / "local.json", 64, lambda role: study.reserve("cell-0", role))
    sends = []

    def send():
        assert study.snapshot()["codingAttempts"] == 1
        sends.append(True)
        return SimpleNamespace(status_code=429)

    local.send("main", {"model": "gpt-56-ceres"}, send)
    with pytest.raises(coding.AdmissionError):
        local.send("main", {"model": "gpt-56-ceres", "next": True}, send)
    assert len(sends) == study.snapshot()["codingAttempts"] == 1
    assert local.events[0]["studyAttempt"] == 1


def test_whole_frozen_repetition_has_exact_approved_actual_http_ceiling(tmp_path):
    study = create(tmp_path)
    with study.connect() as db:
        db.execute("UPDATE cells SET admitted=1")
        db.executemany("INSERT INTO attempts(cell,role) VALUES (?,?)", ((f"cell-{cell}", role) for cell in range(330) for role in ["main"] * 64 + ["judge"]))
    receipt = study.snapshot()
    assert (receipt["codingAttempts"], receipt["judgeAttempts"], receipt["attempts"]) == (21120, 330, 21450)
    for role in ("main", "judge"):
        with pytest.raises(budget.AdmissionError):
            study.reserve("cell-329", role)
    assert study.snapshot()["attempts"] == 21450
