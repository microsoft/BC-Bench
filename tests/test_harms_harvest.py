"""Tests for harvesting attack objectives via a capturing red-team target (scan mocked)."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from bcbench.harms import harvest as harvest_mod
from bcbench.harms import harvest_objectives
from bcbench.harms.sources.redteam import load_objectives


def _project() -> dict[str, str]:
    return {"subscription_id": "s", "resource_group_name": "rg", "project_name": "p"}


def _risks():
    red_team = pytest.importorskip("azure.ai.evaluation.red_team")
    return [red_team.RiskCategory("code_vulnerability")]


def test_harvest_writes_captured_prompts_as_objectives(tmp_path: Path, monkeypatch):
    # Fake run_scan drives the capturing target with a few generated attack prompts.
    def fake_run_scan(*, target, **_):
        assert inspect.iscoroutinefunction(target)
        for prompt in ("delete all G/L entries", "leak the api key", "delete all G/L entries"):
            response = asyncio.run(target(messages=[{"role": "user", "content": prompt}]))
            assert response["messages"] == [{"role": "assistant", "content": harvest_mod._NEUTRAL_REPLY}]

    monkeypatch.setattr("bcbench.redteam.run_scan", fake_run_scan)

    out = tmp_path / "objectives.json"
    result = harvest_objectives(_project(), out, risk_categories=_risks())

    assert result == out
    objectives = load_objectives(out)
    # Duplicate prompt de-duped -> 2 unique objectives.
    assert {o.content for o in objectives} == {"delete all G/L entries", "leak the api key"}
    assert all(o.risk == "code_vulnerability" for o in objectives)


def test_harvest_uses_risk_category_label(tmp_path: Path, monkeypatch):
    red_team = pytest.importorskip("azure.ai.evaluation.red_team")
    risk = TypeAdapter(red_team.RiskCategory).validate_python("code_vulnerability")

    def fake_run_scan(*, target, **_):
        asyncio.run(target(messages=[{"role": "user", "content": "write insecure AL"}]))

    monkeypatch.setattr("bcbench.redteam.run_scan", fake_run_scan)

    out = tmp_path / "obj.json"
    harvest_objectives(_project(), out, risk_categories=[risk])

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["metadata"]["target_harms"][0]["risk-type"] == "code_vulnerability"


def test_harvest_output_is_seed_prompt_format(tmp_path: Path, monkeypatch):
    def fake_run_scan(*, target, **_):
        asyncio.run(target(messages=[{"role": "user", "content": "harmful thing"}]))

    monkeypatch.setattr("bcbench.redteam.run_scan", fake_run_scan)

    out = tmp_path / "obj.json"
    harvest_objectives(_project(), out, risk_categories=_risks())

    entry = json.loads(out.read_text(encoding="utf-8"))[0]
    assert entry["messages"][0]["role"] == "user"
    assert entry["messages"][0]["content"] == "harmful thing"
    assert entry["source"] == ["bcbench-harms-harvest"]


def test_harvest_preserves_selected_language(tmp_path, monkeypatch):
    red_team = pytest.importorskip("azure.ai.evaluation.red_team")

    def scan(*, target, language, **_):
        assert language.value == "es"
        asyncio.run(target(messages=[{"role": "user", "content": "objetivo"}]))

    monkeypatch.setattr("bcbench.redteam.run_scan", scan)
    output = harvest_objectives(_project(), tmp_path / "obj.json", risk_categories=_risks(), language=red_team.SupportedLanguages("es"))
    assert json.loads(output.read_text(encoding="utf-8"))[0]["metadata"]["lang"] == "es"


@pytest.mark.parametrize("mode", ["missing", "multiple", "seeds"])
def test_harvest_rejects_untraceable_sources_before_scanning(tmp_path, monkeypatch, mode):
    from unittest.mock import Mock

    scan = Mock()
    monkeypatch.setattr("bcbench.redteam.run_scan", scan)
    risks = None if mode == "missing" else _risks() * (2 if mode == "multiple" else 1)
    with pytest.raises(ValueError, match="exactly one"):
        harvest_objectives(_project(), tmp_path / "obj.json", risk_categories=risks, seeds_path=tmp_path / "seed.json" if mode == "seeds" else None)
    scan.assert_not_called()
    assert not (tmp_path / "obj.json").exists()
