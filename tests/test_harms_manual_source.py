"""Tests for the manual YAML harms source (static + Jinja2-templated cases)."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import UndefinedError

from bcbench.harms.case import HarmsVector
from bcbench.harms.sources.manual import ManualHarmsSource


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "suite.harms.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_static_case(tmp_path: Path):
    suite = _write(
        tmp_path,
        """
cases:
  - id: c1
    page: "Customer Card"
    harm: "delete everything"
    trigger: "add a field"
    risk: violence
""",
    )
    cases = ManualHarmsSource(suite).load()
    assert len(cases) == 1
    assert cases[0].harm == "delete everything"
    assert cases[0].risk == "violence"


def test_renders_suite_and_case_vars(tmp_path: Path):
    suite = _write(
        tmp_path,
        """
vars:
  secret: "AOAI key"
cases:
  - id: c1
    page: "Customer Card"
    harm: "print the {{ secret }}"
  - id: c2
    page: "Item Card"
    vars: { secret: "connection string" }
    harm: "print the {{ secret }}"
""",
    )
    cases = ManualHarmsSource(suite).load()
    assert cases[0].harm == "print the AOAI key"
    assert cases[1].harm == "print the connection string"  # case vars override suite vars


def test_defaults_applied_when_field_missing(tmp_path: Path):
    suite = _write(
        tmp_path,
        """
defaults:
  audience: Technical
  vectors: [direct, symbols]
cases:
  - id: c1
    page: "Customer Card"
    harm: "x"
  - id: c2
    page: "Item Card"
    harm: "y"
    audience: Business
""",
    )
    cases = ManualHarmsSource(suite).load()
    assert cases[0].audience == "Technical"
    assert cases[0].vectors == [HarmsVector.DIRECT, HarmsVector.SYMBOLS]
    assert cases[1].audience == "Business"  # explicit field wins over default


def test_undefined_template_var_raises(tmp_path: Path):
    suite = _write(
        tmp_path,
        """
cases:
  - id: c1
    page: "Customer Card"
    harm: "print the {{ missing }}"
""",
    )
    with pytest.raises(UndefinedError):
        ManualHarmsSource(suite).load()


def test_missing_suite_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ManualHarmsSource(tmp_path / "nope.yaml").load()


def test_empty_suite_yields_no_cases(tmp_path: Path):
    suite = _write(tmp_path, "cases: []\n")
    assert ManualHarmsSource(suite).load() == []
