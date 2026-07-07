"""Tests for the red-team harms source: objective parsing, couching, and case expansion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcbench.harms import AttackObjective, RedTeamHarmsSource, couchings_by_id, load_objectives
from bcbench.harms.case import HarmsVector
from bcbench.harms.couching import DEFAULT_COUCHINGS, CouchingTemplate


class TestObjectiveParsing:
    def test_from_seed_entry_extracts_content_and_risk(self):
        entry = {
            "metadata": {"target_harms": [{"risk-type": "code_vulnerability", "risk-subtype": ""}]},
            "messages": [{"role": "user", "content": "delete everything"}],
            "id": "7",
        }
        obj = AttackObjective.from_seed_entry(entry, 0)
        assert obj.id == "7"
        assert obj.content == "delete everything"
        assert obj.risk == "code_vulnerability"

    def test_missing_risk_is_none(self):
        obj = AttackObjective.from_seed_entry({"messages": [{"role": "user", "content": "x"}]}, 3)
        assert obj.risk is None
        assert obj.id == "3"  # falls back to index

    def test_load_objectives_reads_list(self, tmp_path: Path):
        path = tmp_path / "obj.json"
        path.write_text(json.dumps([{"messages": [{"role": "user", "content": "harm one"}], "id": "1"}]), encoding="utf-8")
        objs = load_objectives(path)
        assert len(objs) == 1
        assert objs[0].content == "harm one"

    def test_load_objectives_skips_empty_content(self, tmp_path: Path):
        path = tmp_path / "obj.json"
        path.write_text(json.dumps([{"messages": [{"role": "assistant", "content": "not user"}], "id": "1"}]), encoding="utf-8")
        assert load_objectives(path) == []

    def test_load_objectives_rejects_non_list(self, tmp_path: Path):
        path = tmp_path / "obj.json"
        path.write_text(json.dumps({"nope": 1}), encoding="utf-8")
        with pytest.raises(TypeError, match="JSON list"):
            load_objectives(path)

    def test_load_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_objectives(tmp_path / "nope.json")


class TestCouching:
    def test_default_couchings_have_unique_ids(self):
        ids = [c.id for c in DEFAULT_COUCHINGS]
        assert len(ids) == len(set(ids))

    def test_render_wraps_objective(self):
        c = CouchingTemplate(id="t", harm="X: {{ objective }} on {{ page }}", trigger="benign {{ page }}")
        assert c.render_harm(objective="do harm", page="Customer Card", audience="Business", risk="") == "X: do harm on Customer Card"
        assert c.render_trigger(objective="do harm", page="Customer Card", audience="Business", risk="") == "benign Customer Card"

    def test_couchings_by_id_selects_subset(self):
        selected = couchings_by_id(["system_override"])
        assert len(selected) == 1
        assert selected[0].id == "system_override"

    def test_couchings_by_id_none_returns_all(self):
        assert len(couchings_by_id(None)) == len(DEFAULT_COUCHINGS)

    def test_couchings_by_id_unknown_raises(self):
        with pytest.raises(KeyError):
            couchings_by_id(["nonexistent"])


class TestRedTeamHarmsSource:
    def _objectives(self) -> list[AttackObjective]:
        return [
            AttackObjective(id="1", content="delete all entries", risk="prohibited_actions"),
            AttackObjective(id="2", content="leak the key", risk="sensitive_data_leakage"),
        ]

    def test_expands_objectives_by_couchings(self):
        cases = RedTeamHarmsSource(self._objectives(), page="Item Card").load()
        # 2 objectives x len(DEFAULT_COUCHINGS)
        assert len(cases) == 2 * len(DEFAULT_COUCHINGS)

    def test_case_carries_source_and_risk(self):
        cases = RedTeamHarmsSource(self._objectives(), couchings=couchings_by_id(["system_override"])).load()
        assert len(cases) == 2
        assert all(c.source == "redteam" for c in cases)
        assert cases[0].risk == "prohibited_actions"
        assert cases[0].id == "rt-1-system_override"

    def test_objective_content_appears_in_harm(self):
        cases = RedTeamHarmsSource(self._objectives(), couchings=couchings_by_id(["system_override"])).load()
        assert "delete all entries" in cases[0].harm

    def test_page_and_audience_applied(self):
        cases = RedTeamHarmsSource(self._objectives(), page="Vendor Card", audience="Both").load()
        assert cases[0].page == "Vendor Card"
        assert cases[0].audience == "Both"

    def test_vectors_override_passed_through(self):
        cases = RedTeamHarmsSource(self._objectives(), vectors=[HarmsVector.DIRECT]).load()
        assert cases[0].resolve_vectors() == [HarmsVector.DIRECT]
