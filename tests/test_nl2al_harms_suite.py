from pathlib import Path

import pytest
from pydantic import ValidationError

from bcbench.agent.bcal.harms.case import HarmsVector
from bcbench.agent.bcal.harms.suite import load_suite


def test_case_overrides_suite_defaults(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "defaults: {audience: Technical, vectors: [direct, symbols]}\n"
        "cases:\n"
        "  - {id: first, page: Customer Card, harm: adversarial text}\n"
        "  - {id: second, page: Item Card, harm: other text, audience: Business}\n",
        encoding="utf-8",
    )
    first, second = load_suite(path)
    assert first.audience == "Technical"
    assert first.vectors == [HarmsVector.DIRECT, HarmsVector.SYMBOLS]
    assert second.audience == "Business"


@pytest.mark.parametrize(
    "content",
    [
        "cases: []",
        "cases: [{id: first, harm: missing page}]",
        "cases: [{id: same, page: Item Card, harm: one}, {id: same, page: Item Card, harm: two}]",
        "vars: {unused: value}\ncases: [{id: first, page: Item Card, harm: text}]",
    ],
)
def test_invalid_suite_rejected_before_capture(tmp_path, content):
    path = tmp_path / "cases.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        load_suite(path)


@pytest.mark.parametrize("name", ["comprehensive", "code-vulnerability"])
def test_retained_suite_produces_indirect_fixtures(name):
    cases = load_suite(Path(__file__).parents[1] / "dataset" / "nl2al" / "harms" / f"{name}.harms.yaml")
    for case in cases:
        fixture = case.fixture_manifest_for(HarmsVector.PAGE_INSPECTOR)
        assert fixture is not None
        assert fixture["injections"][0]["payload"] == case.harm
        assert case.prompt_for(HarmsVector.PAGE_INSPECTOR) != case.harm
