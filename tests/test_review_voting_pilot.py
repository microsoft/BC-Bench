import pytest

from tools.review_voting_pilot import aggregate, validate_evidence, validate_votes


def decision(key, verdict="supported"):
    return {
        "id": key,
        "verdict": verdict,
        "trigger": "input",
        "call_path_and_guards": "caller",
        "impact": "impact",
        "counterevidence": "none found",
        "evidence": [{"tree": "source", "file": "file.al", "line_start": 1, "line_end": 1, "quote": "code"}],
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [decision("F001"), decision("F001")],
        [decision("unknown")],
    ],
)
def test_rejects_missing_duplicate_unknown_or_invalid_ids(payload):
    with pytest.raises(ValueError, match="Missing, duplicate, or unexpected"):
        validate_votes(["F001"], payload)


def test_rejects_duplicate_candidate_ids():
    with pytest.raises(ValueError, match="Duplicate candidate"):
        validate_votes(["F001", "F001"], [decision("F001")])


def test_rejects_non_array_output():
    with pytest.raises(TypeError, match="JSON array"):
        validate_votes(["F001"], {"F001": "supported"})


def test_failed_voter_is_not_a_negative_vote():
    valid = validate_votes(["F001"], [decision("F001")])
    with pytest.raises(ValueError, match="failure is not a vote"):
        aggregate(["F001"], [valid, valid, None])


def test_threshold_and_preselected_first_voter():
    ids = ["F001", "F002", "F003"]
    voters = [
        validate_votes(ids, [decision("F001"), decision("F002", "refuted"), decision("F003", "insufficient_evidence")]),
        validate_votes(ids, [decision("F001", "refuted"), decision("F002"), decision("F003", "insufficient_evidence")]),
        validate_votes(ids, [decision("F001", "insufficient_evidence"), decision("F002"), decision("F003")]),
    ]
    assert aggregate(ids, voters) == {"A": ids, "B": ["F001"], "C": ["F002"]}


def test_zero_candidates_needs_no_calls():
    assert aggregate([], []) == {"A": [], "B": [], "C": []}


def test_evidence_is_checked_against_real_source(tmp_path):
    (tmp_path / "file.al").write_text("code\n")
    votes = validate_votes(["F001"], [decision("F001")])
    validate_evidence(votes, tmp_path, tmp_path)
    votes[0].evidence[0].quote = "invented"
    with pytest.raises(ValueError, match="quote not present"):
        validate_evidence(votes, tmp_path, tmp_path)


def test_evidence_cannot_escape_allowed_tree(tmp_path):
    votes = validate_votes(["F001"], [decision("F001")])
    votes[0].evidence[0].file = "../outside.al"
    with pytest.raises(ValueError, match="invalid evidence path"):
        validate_evidence(votes, tmp_path, tmp_path)
