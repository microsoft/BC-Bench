"""Tests for the harms runner: vector expansion, fixture generation, and bcal invocation (mocked)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bcbench.harms import runner as harms_runner
from bcbench.harms.case import HarmsCase, HarmsVector
from tests.conftest import create_nl2al_entry


@pytest.fixture(autouse=True)
def _stub_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harms_runner, "_load_base_entry", create_nl2al_entry)
    monkeypatch.setattr(harms_runner, "ensure_package_cache", lambda *_a, **_k: None)


def _cases() -> list[HarmsCase]:
    return [HarmsCase.model_validate({"id": "c1", "harm": "bad thing", "page": "Customer Card", "trigger": "benign task"})]


def _backend() -> Any:
    from bcbench.agent.bcal import BCalBackendConfig
    from bcbench.types import BCalLLMBackend

    return BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint="https://aoai.example/", deployment="gpt-5.2")


def test_dry_run_writes_fixtures_but_skips_bcal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    called = {"count": 0}
    monkeypatch.setattr(harms_runner, "run_bcal_prompt", lambda *a, **k: called.__setitem__("count", called["count"] + 1) or "x")

    trials = harms_runner.run_harms_suite(_cases(), _backend(), tmp_path, vectors=[HarmsVector.DIRECT, HarmsVector.SYMBOLS], dry_run=True)

    assert called["count"] == 0
    assert [t.executed for t in trials] == [False, False]
    # direct -> no fixture; symbols -> fixture file written
    assert trials[0].fixture_path is None
    assert trials[1].fixture_path is not None
    assert Path(trials[1].fixture_path).exists()
    assert (tmp_path / "trials.jsonl").exists()


def test_executed_run_calls_bcal_per_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: list[dict[str, Any]] = []

    def fake_bcal(entry: Any, prompt: str, cache: Path, export: Path, backend: Any, **kwargs: Any) -> str:
        captured.append({"prompt": prompt, "fixture": kwargs.get("harms_fixture_path")})
        return f"bcal-output-for::{prompt}"

    monkeypatch.setattr(harms_runner, "run_bcal_prompt", fake_bcal)

    trials = harms_runner.run_harms_suite(_cases(), _backend(), tmp_path, vectors=[HarmsVector.DIRECT, HarmsVector.PAGE_INSPECTOR])

    assert len(captured) == 2
    # direct: prompt is the harm, no fixture
    assert captured[0]["prompt"] == "bad thing"
    assert captured[0]["fixture"] is None
    # indirect: prompt is the trigger, a fixture path is supplied
    assert captured[1]["prompt"] == "benign task"
    assert captured[1]["fixture"] is not None
    assert all(t.executed for t in trials)
    assert trials[0].response == "bcal-output-for::bad thing"


def test_limit_caps_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(harms_runner, "run_bcal_prompt", lambda *a, **k: "x")
    cases = [
        HarmsCase.model_validate({"id": "c1", "harm": "a", "page": "P"}),
        HarmsCase.model_validate({"id": "c2", "harm": "b", "page": "P"}),
    ]
    trials = harms_runner.run_harms_suite(cases, _backend(), tmp_path, limit=1, vectors=[HarmsVector.DIRECT], dry_run=True)
    assert {t.case_id for t in trials} == {"c1"}


def test_channels_labelled_per_vector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(harms_runner, "run_bcal_prompt", lambda *a, **k: "x")
    trials = harms_runner.run_harms_suite(_cases(), _backend(), tmp_path, vectors=[HarmsVector.DIRECT, HarmsVector.ASK_USER], dry_run=True)
    by_vector = {t.vector: t.channel.value for t in trials}
    assert by_vector[HarmsVector.DIRECT] == "direct"
    assert by_vector[HarmsVector.ASK_USER] == "indirect"
