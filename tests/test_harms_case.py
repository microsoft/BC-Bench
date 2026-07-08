"""Tests for the vector-invariant HarmsCase model and per-vector fixture expansion."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bcbench.harms.case import DEFAULT_VECTOR_MATRIX, HarmsCase, HarmsChannel, HarmsVector


def _case(**overrides: object) -> HarmsCase:
    fields: dict[str, object] = {"id": "c1", "harm": "do something bad", "page": "Customer Card"}
    fields.update(overrides)
    return HarmsCase.model_validate(fields)


class TestVectorExpansion:
    def test_default_matrix_is_direct_plus_all_seams(self):
        assert _case().resolve_vectors() == list(DEFAULT_VECTOR_MATRIX)

    def test_case_vectors_override_default(self):
        case = _case(vectors=[HarmsVector.DIRECT, HarmsVector.PAGE_INSPECTOR])
        assert case.resolve_vectors() == [HarmsVector.DIRECT, HarmsVector.PAGE_INSPECTOR]

    def test_runtime_matrix_overrides_case(self):
        case = _case(vectors=[HarmsVector.DIRECT, HarmsVector.PAGE_INSPECTOR])
        assert case.resolve_vectors([HarmsVector.SYMBOLS]) == [HarmsVector.SYMBOLS]

    def test_resolve_dedupes_preserving_order(self):
        case = _case(vectors=[HarmsVector.DIRECT, HarmsVector.DIRECT, HarmsVector.SYMBOLS])
        assert case.resolve_vectors() == [HarmsVector.DIRECT, HarmsVector.SYMBOLS]


class TestChannelClassification:
    def test_direct_is_upia(self):
        assert HarmsVector.DIRECT.channel is HarmsChannel.DIRECT

    @pytest.mark.parametrize("vector", [v for v in HarmsVector if v is not HarmsVector.DIRECT])
    def test_seams_are_indirect(self, vector: HarmsVector):
        assert vector.channel is HarmsChannel.INDIRECT


class TestScoringMetadata:
    def test_defaults_are_none(self):
        case = _case()
        assert case.rule is None
        assert case.detector is None
        assert case.expected is None

    def test_accepts_rule_and_expected(self):
        case = _case(rule="secrets-isolated-storage", expected="a secret stored in an ordinary Text field")
        assert case.rule == "secrets-isolated-storage"
        assert case.expected == "a secret stored in an ordinary Text field"

    def test_parses_detector_signature(self):
        case = _case(detector={"must_match": ["HttpClient", r"Post\("], "must_not_match": ["IsolatedStorage"]})
        assert case.detector is not None
        assert case.detector.must_match == ["HttpClient", r"Post\("]
        assert case.detector.must_not_match == ["IsolatedStorage"]
        assert case.detector.is_empty() is False

    def test_empty_detector_reports_empty(self):
        case = _case(detector={})
        assert case.detector is not None
        assert case.detector.is_empty() is True

    def test_detector_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            _case(detector={"must_match": ["x"], "bogus": ["y"]})


class TestPromptSelection:
    def test_direct_uses_harm_as_prompt(self):
        assert _case().prompt_for(HarmsVector.DIRECT) == "do something bad"

    def test_indirect_uses_trigger(self):
        case = _case(trigger="Add a benign field.")
        assert case.prompt_for(HarmsVector.PAGE_INSPECTOR) == "Add a benign field."

    def test_indirect_without_trigger_falls_back_to_page(self):
        prompt = _case().prompt_for(HarmsVector.SYMBOLS)
        assert "Customer Card" in prompt


class TestFixtureManifest:
    def test_direct_has_no_fixture(self):
        assert _case().fixture_manifest_for(HarmsVector.DIRECT) is None

    def test_seam_injects_harm_as_payload(self):
        manifest = _case().fixture_manifest_for(HarmsVector.SYMBOLS)
        assert manifest == {"injections": [{"vector": "symbols", "payload": "do something bad"}]}

    def test_placement_fields_included_for_matching_vector(self):
        case = _case(placement={HarmsVector.PAGE_INSPECTOR: {"object": "Customer Card", "property": "ToolTip", "mode": "append"}})
        injection = case.fixture_manifest_for(HarmsVector.PAGE_INSPECTOR)["injections"][0]
        assert injection["object"] == "Customer Card"
        assert injection["property"] == "ToolTip"
        assert injection["mode"] == "append"

    def test_irrelevant_placement_fields_are_dropped_for_vector(self):
        # `object`/`property` are not valid for the translations vector; they must not leak into the manifest.
        case = _case(placement={HarmsVector.TRANSLATIONS: {"object": "X", "mode": "prepend"}})
        injection = case.fixture_manifest_for(HarmsVector.TRANSLATIONS)["injections"][0]
        assert "object" not in injection
        assert injection["mode"] == "prepend"

    def test_ask_user_limit_included(self):
        case = _case(placement={HarmsVector.ASK_USER: {"limit": 1}})
        injection = case.fixture_manifest_for(HarmsVector.ASK_USER)["injections"][0]
        assert injection["limit"] == 1

    def test_packages_part_included(self):
        case = _case(placement={HarmsVector.PACKAGES: {"part": "source"}})
        injection = case.fixture_manifest_for(HarmsVector.PACKAGES)["injections"][0]
        assert injection["part"] == "source"


class TestValidation:
    def test_unknown_vector_rejected(self):
        with pytest.raises(ValidationError):
            _case(vectors=["telepathy"])

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValidationError):
            _case(placement={HarmsVector.SYMBOLS: {"mode": "obliterate"}})

    def test_unknown_part_rejected(self):
        with pytest.raises(ValidationError):
            _case(placement={HarmsVector.PACKAGES: {"part": "everything"}})

    def test_empty_harm_rejected(self):
        with pytest.raises(ValidationError):
            _case(harm="")

    def test_negative_limit_rejected(self):
        with pytest.raises(ValidationError):
            _case(placement={HarmsVector.ASK_USER: {"limit": -1}})

    def test_extra_placement_field_rejected(self):
        with pytest.raises(ValidationError):
            _case(placement={HarmsVector.SYMBOLS: {"bogus": "x"}})
