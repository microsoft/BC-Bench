import hashlib
import json
import subprocess

import pytest
from pydantic import ValidationError

from tools import review_voting_pilot as pilot
from tools.review_voting_evidence import (
    EvidenceBundle,
    ProtectedView,
    aggregate,
    check_bundle,
    digest_json,
    evidence_prompt,
    file_digest,
    resolve_evidence,
    tree_digest,
    validate_votes,
)


@pytest.fixture(autouse=True)
def forbid_real_subprocesses(monkeypatch):
    monkeypatch.setattr(pilot.subprocess, "run", lambda *args, **kwargs: pytest.fail("Tests must never launch a model or subprocess"))


@pytest.fixture
def captured(tmp_path):
    source = tmp_path / "source"
    knowledge = tmp_path / "knowledge"
    source.mkdir()
    knowledge.mkdir()
    source_text = "procedure Validate()\nbegin\n    exit;\nend;\n"
    knowledge_text = "# Guidance\n\nChoose access deliberately.\n"
    (source / "helper.al").write_text(source_text, encoding="utf-8")
    (knowledge / "guide.md").write_text(knowledge_text, encoding="utf-8")
    candidates = [{"id": "F001", "comment": {"file": "helper.al", "body": "Example claim"}}]
    patch = "synthetic fixture diff"
    bundle = EvidenceBundle(
        capture_provider="policy-filtered-view",
        source_sha256=tree_digest(source),
        knowledge_sha256=tree_digest(knowledge),
        candidates_sha256=digest_json(candidates),
        diff_sha256=hashlib.sha256(patch.encode()).hexdigest(),
        views=(
            ProtectedView(
                capture_id="fixture-source",
                tree="source",
                file="helper.al",
                file_sha256=file_digest(source / "helper.al"),
                line_start=1,
                line_end=4,
                status="available",
                text=source_text,
                reason="Known non-sensitive synthetic fixture",
            ),
            ProtectedView(
                capture_id="fixture-knowledge",
                tree="knowledge",
                file="guide.md",
                file_sha256=file_digest(knowledge / "guide.md"),
                line_start=3,
                line_end=3,
                status="available",
                text="Choose access deliberately.",
                reason="Known fixture range",
            ),
        ),
    )
    return source, knowledge, candidates, patch, bundle


def decision(bundle, key="F001", verdict="supported", status="available"):
    return {
        "id": key,
        "verdict": verdict,
        "trigger": "input",
        "call_path_and_guards": "caller unknown",
        "impact": "example impact",
        "counterevidence": "intent unknown",
        "evidence_ids": list(bundle.indexed_views()),
        "source_view_status": status,
    }


def resolved(bundle, ids=("F001",), verdicts=("supported",)):
    return resolve_evidence(validate_votes(list(ids), [decision(bundle, key, verdict) for key, verdict in zip(ids, verdicts, strict=True)]), bundle)


def changed_bundle(bundle, **changes):
    return EvidenceBundle.model_validate_json(json.dumps(bundle.model_dump(mode="json") | changes))


@pytest.mark.parametrize("payload", [[], [{"id": "unknown"}], [{"id": "F001"}, {"id": "F001"}]])
def test_missing_or_incomplete_decisions_rejected(payload):
    with pytest.raises(ValueError, match=r"Missing|validation"):
        validate_votes(["F001"], payload)


def test_unknown_duplicate_and_missing_candidate_ids(captured):
    bundle = captured[-1]
    for payload in ([decision(bundle, "unknown")], [decision(bundle), decision(bundle)], []):
        with pytest.raises(ValueError, match="Missing, duplicate, or unexpected"):
            validate_votes(["F001"], payload)
    with pytest.raises(ValueError, match="Duplicate candidate"):
        validate_votes(["F001", "F001"], [])
    with pytest.raises(TypeError, match="JSON array"):
        validate_votes(["F001"], {})


def test_immutable_ids_resolve_authoritative_ranges_and_content(captured):
    bundle = captured[-1]
    roundtrip = EvidenceBundle.model_validate_json(bundle.model_dump_json())
    assert roundtrip.indexed_views() == bundle.indexed_views()
    result = resolved(bundle)[0]
    assert result.evidence[1].view.file == "guide.md"
    assert result.evidence[1].view.line_start == result.evidence[1].view.line_end == 3
    assert result.evidence[1].view.text == "Choose access deliberately."
    assert result.evidence_resolution == "resolved"
    assert result.semantic_correctness == "not_assessed"
    with pytest.raises(ValidationError, match="frozen"):
        bundle.views[0].line_start = 2


def test_model_cannot_author_a_quote_or_wrong_line_number(captured):
    for field, value in (("quote", "invented"), ("line_start", 22), ("file", "other.al")):
        payload = decision(captured[-1]) | {field: value}
        with pytest.raises(ValidationError, match="Extra inputs"):
            validate_votes(["F001"], [payload])


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "no-source"])
def test_invalid_evidence_references(captured, kind):
    bundle = captured[-1]
    payload = decision(bundle)
    keys = payload["evidence_ids"]
    payload["evidence_ids"] = ["E-unknown"] if kind == "unknown" else [keys[0], keys[0]] if kind == "duplicate" else [keys[1]]
    with pytest.raises(ValueError, match=r"unknown|duplicate|source evidence"):
        resolve_evidence(validate_votes(["F001"], [payload]), bundle)


def test_incorrect_real_reference_does_not_prove_claim(captured):
    result = resolved(captured[-1])[0]
    # Authentic source selection cannot prove this fixture's unsubstantiated claim.
    assert result.decision.verdict == "supported"
    assert result.semantic_correctness == "not_assessed"
    assert result.evidence_resolution == "resolved"


@pytest.mark.parametrize("change", ["source", "knowledge", "new-file", "deleted-file"])
def test_changed_snapshot_rejected(captured, change):
    source, knowledge, candidates, patch, bundle = captured
    if change == "deleted-file":
        (source / "helper.al").unlink()
    else:
        path = knowledge / "guide.md" if change == "knowledge" else source / ("new.al" if change == "new-file" else "helper.al")
        path.write_text("different safe fixture\n")
    with pytest.raises(ValueError, match="snapshot is stale"):
        check_bundle(bundle, bundle.sha256, source, knowledge, candidates, patch)


def test_tampered_bundle_and_stale_capture_identity(captured):
    source, knowledge, candidates, patch, bundle = captured
    views = bundle.model_dump(mode="json")["views"]
    views[1]["line_start"] = views[1]["line_end"] = 2
    altered = changed_bundle(bundle, views=views)
    assert set(altered.indexed_views()).isdisjoint(bundle.indexed_views())
    with pytest.raises(ValueError, match="bundle changed"):
        check_bundle(altered, bundle.sha256, source, knowledge, candidates, patch)
    views[0]["file_sha256"] = "0" * 64
    stale = changed_bundle(bundle, views=views)
    with pytest.raises(ValueError, match="Captured file identity"):
        check_bundle(stale, stale.sha256, source, knowledge, candidates, patch)


@pytest.mark.parametrize("field", ["candidates", "diff"])
def test_changed_inputs_rejected(captured, field):
    source, knowledge, candidates, patch, bundle = captured
    with pytest.raises(ValueError, match="candidate/diff identity"):
        check_bundle(bundle, bundle.sha256, source, knowledge, [] if field == "candidates" else candidates, "new" if field == "diff" else patch)


@pytest.mark.parametrize("status", ["redacted", "unavailable"])
def test_unavailable_views_are_explicit_not_negative_votes(captured, status):
    bundle = captured[-1]
    views = bundle.model_dump(mode="json")["views"]
    views[0].update(status=status, text=None, reason="Protected view cannot be safely established")
    bundle = changed_bundle(bundle, views=views)
    payload = decision(bundle, verdict="insufficient_evidence", status=status)
    votes = resolve_evidence(validate_votes(["F001"], [payload]), bundle)
    assert votes[0].evidence_resolution == status
    assert votes[0].evidence[0].view.text is None
    with pytest.raises(ValueError, match="not a negative vote"):
        aggregate(["F001"], [votes] * 3, bundle)
    for verdict in ("supported", "refuted"):
        payload["verdict"] = verdict
        with pytest.raises(ValueError, match="cannot support a verdict"):
            resolve_evidence(validate_votes(["F001"], [payload]), bundle)


def test_model_observed_redaction_overrides_available_capture(captured):
    bundle = captured[-1]
    payload = decision(bundle, verdict="insufficient_evidence", status="redacted")
    votes = resolve_evidence(validate_votes(["F001"], [payload]), bundle)
    assert votes[0].evidence_resolution == "redacted"
    with pytest.raises(ValueError, match="not a negative vote"):
        aggregate(["F001"], [votes] * 3, bundle)


@pytest.mark.parametrize(
    "changes",
    [
        {"line_start": 4, "line_end": 2},
        {"line_end": 9},
        {"file": "../outside.al"},
        {"file": "C:\\outside.al"},
        {"status": "redacted"},
    ],
)
def test_invalid_capture_metadata(captured, changes):
    view = captured[-1].views[0].model_dump(mode="json") | changes
    with pytest.raises(ValueError, match=r"range|path|must not carry text"):
        ProtectedView.model_validate(view)


def test_duplicate_capture_ranges_rejected(captured):
    bundle = captured[-1]
    views = bundle.model_dump(mode="json")["views"]
    with pytest.raises(ValueError, match="Duplicate captured evidence range"):
        changed_bundle(bundle, views=[*views, views[0]])


def test_failed_or_missing_voter_blocks_aggregation(captured):
    bundle = captured[-1]
    valid = resolved(bundle)
    for voters in ([valid, valid, None], [valid, valid]):
        with pytest.raises(ValueError, match="failure is not a vote"):
            aggregate(["F001"], voters, bundle)


def test_threshold_preselected_first_voter_and_resolved_uncertainty(captured):
    bundle = captured[-1]
    ids = ["F001", "F002", "F003"]
    voters = [
        resolved(bundle, ids, ("supported", "refuted", "insufficient_evidence")),
        resolved(bundle, ids, ("refuted", "supported", "insufficient_evidence")),
        resolved(bundle, ids, ("insufficient_evidence", "supported", "supported")),
    ]
    assert aggregate(ids, voters, bundle) == {"A": ids, "B": ["F001"], "C": ["F002"]}
    assert aggregate([], [], bundle) == {"A": [], "B": [], "C": []}


def test_stale_resolved_votes_rejected(captured):
    bundle = captured[-1]
    updated = changed_bundle(bundle, source_sha256="0" * 64)
    with pytest.raises(ValueError, match="unknown evidence reference"):
        aggregate(["F001"], [resolved(bundle)] * 3, updated)


def test_same_gold_blind_prompt_for_all_voters(captured):
    _, _, candidates, patch, bundle = captured
    prompts = [evidence_prompt(bundle, candidates) for _ in range(3)]
    assert len(set(prompts)) == 1
    assert patch not in prompts[0]
    assert "expected_comments" not in prompts[0]
    assert "ignored_comments" not in prompts[0]
    assert "protected-views-v2" in prompts[0]


def test_verifier_wiring_offline_only(captured, tmp_path, monkeypatch):
    source, knowledge, candidates, patch, bundle = captured
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pilot.subprocess, "run", fake_run)
    monkeypatch.setattr(pilot, "isolated_environment", lambda _: {})
    monkeypatch.setattr(pilot, "parse_output", lambda _: (None, json.dumps([decision(bundle)])))
    folder = tmp_path / "voter"
    votes = pilot.run_verifier(folder, source, knowledge, patch, candidates, "not-a-real-cli", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert len(calls) == 1
    assert "--available-tools=none" in calls[0]
    assert "--add-dir" not in calls[0]
    assert votes[0].semantic_correctness == "not_assessed"
    invocation = json.loads((folder / "invocation.json").read_text())
    assert invocation["bundle_sha256"] == bundle.sha256
    assert invocation["adapter_version"] == "evidence-ids-v2"
    with pytest.raises(FileExistsError):
        pilot.run_verifier(folder, source, knowledge, patch, candidates, "not-a-real-cli", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert len(calls) == 1


def test_source_unavailable_blocks_before_any_subprocess(captured, tmp_path, monkeypatch):
    source, knowledge, candidates, patch, bundle = captured
    views = bundle.model_dump(mode="json")["views"]
    views[0].update(status="unavailable", text=None)
    bundle = changed_bundle(bundle, views=views)
    monkeypatch.setattr(pilot.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not invoke a model"))
    with pytest.raises(ValueError, match="Source view unavailable"):
        pilot.run_verifier(tmp_path / "voter", source, knowledge, patch, candidates, "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256)


@pytest.mark.parametrize("exit_code", [1, 124])
def test_subprocess_error_is_not_a_vote(captured, tmp_path, monkeypatch, exit_code):
    source, knowledge, candidates, patch, bundle = captured
    monkeypatch.setattr(pilot, "isolated_environment", lambda _: {})
    monkeypatch.setattr(pilot.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, exit_code))
    with pytest.raises(RuntimeError, match="Verifier failed"):
        pilot.run_verifier(tmp_path / "voter", source, knowledge, patch, candidates, "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert not (tmp_path / "voter/decisions.json").exists()


def test_timeout_recorded_without_vote_or_retry(captured, tmp_path, monkeypatch):
    source, knowledge, candidates, patch, bundle = captured
    calls = []

    def timeout(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("fake", 1800)

    monkeypatch.setattr(pilot, "isolated_environment", lambda _: {})
    monkeypatch.setattr(pilot.subprocess, "run", timeout)
    folder = tmp_path / "voter"
    with pytest.raises(subprocess.TimeoutExpired):
        pilot.run_verifier(folder, source, knowledge, patch, candidates, "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert len(calls) == 1
    assert json.loads((folder / "process.json").read_text())["status"] == "failed"
    assert not (folder / "decisions.json").exists()


@pytest.mark.parametrize("response", ["", "[]", '{"not":"an array"}'])
def test_invalid_output_preserves_failure(captured, tmp_path, monkeypatch, response):
    source, knowledge, candidates, patch, bundle = captured
    monkeypatch.setattr(pilot, "isolated_environment", lambda _: {})
    monkeypatch.setattr(pilot.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0))
    monkeypatch.setattr(pilot, "parse_output", lambda _: (None, response))
    folder = tmp_path / "voter"
    with pytest.raises((ValueError, TypeError)):
        pilot.run_verifier(folder, source, knowledge, patch, candidates, "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert (folder / "validation-failure.json").exists()
    assert (folder / "final.txt").read_text() == response
    assert not (folder / "decisions.json").exists()


def test_source_changed_during_invocation_rejects_result(captured, tmp_path, monkeypatch):
    source, knowledge, candidates, patch, bundle = captured

    def change_source(args, **kwargs):
        (source / "helper.al").write_text("changed synthetic fixture\n")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pilot, "isolated_environment", lambda _: {})
    monkeypatch.setattr(pilot.subprocess, "run", change_source)
    monkeypatch.setattr(pilot, "parse_output", lambda _: (None, json.dumps([decision(bundle)])))
    folder = tmp_path / "voter"
    with pytest.raises(ValueError, match="snapshot is stale"):
        pilot.run_verifier(folder, source, knowledge, patch, candidates, "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256)
    assert (folder / "validation-failure.json").exists()
    assert not (folder / "decisions.json").exists()


def test_no_raw_source_or_diff_export(captured):
    source, _, candidates, patch, bundle = captured
    # A wholly synthetic sentinel, not hidden/redacted content from the pilot.
    (source / "not-captured.al").write_text("UNCAPTURED_FIXTURE_SENTINEL\n")
    prompt = evidence_prompt(bundle, candidates)
    assert "UNCAPTURED_FIXTURE_SENTINEL" not in prompt
    assert patch not in prompt


def test_gold_fields_not_accepted_as_capture_metadata(captured):
    bundle = captured[-1]
    payload = bundle.model_dump(mode="json") | {"expected_comments": []}
    with pytest.raises(ValidationError, match="Extra inputs"):
        EvidenceBundle.model_validate_json(json.dumps(payload))


def test_zero_candidates_skips_invocation(captured, tmp_path):
    source, knowledge, _, patch, bundle = captured
    bundle = changed_bundle(bundle, candidates_sha256=digest_json([]))
    folder = tmp_path / "no-voter-needed"
    assert pilot.run_verifier(folder, source, knowledge, patch, [], "unused", bundle=bundle, expected_bundle_sha256=bundle.sha256) == []
    assert not folder.exists()


def test_refuted_verdict_resolves_without_model_authored_coordinates(captured):
    vote = resolved(captured[-1], verdicts=("refuted",))[0]
    assert vote.evidence_resolution == "resolved"
    assert vote.decision.verdict == "refuted"
    assert vote.semantic_correctness == "not_assessed"


def test_v1_quote_range_output_is_not_reinterpreted(captured):
    payload = decision(captured[-1])
    payload.pop("evidence_ids")
    payload["evidence"] = [{"tree": "source", "file": "helper.al", "line_start": 22, "line_end": 22, "quote": "synthetic wrong citation"}]
    with pytest.raises(ValidationError, match="validation"):
        validate_votes(["F001"], [payload])
