import json
from pathlib import Path

import pytest

from tools.review_voting_evidence import resolve_evidence, validate_votes, view_records, visible_lines


def events(path, span, text, key="view"):
    return [
        {"type": "tool.execution_start", "data": {"toolName": "view", "toolCallId": key, "arguments": {"path": str(path), "view_range": span}}},
        {"type": "tool.execution_complete", "data": {"toolCallId": key, "success": True, "result": {"content": text}}},
    ]


@pytest.mark.parametrize(
    ("requested", "text", "actual"),
    [
        ([12, 15], "Heading\n\nParagraph\n", (12, ["Heading", "", "Paragraph", ""])),
        ([19, 25], "\nHeading\n\nParagraph\n\nExample\n", (19, ["", "Heading", "", "Paragraph", "", "Example", ""])),
        ([11, 19], "\nHeading\n\nParagraph\n\nRule\n\nAdvice\n", (11, ["", "Heading", "", "Paragraph", "", "Rule", "", "Advice", ""])),
        ([10, 23], "\n".join(["line"] * 13) + "\n", (10, ["line"] * 13 + [""])),
        ([172, 195], "L172:begin\nL173:end;", (172, ["begin", "end;"])),
        ([1, 220], "L20:Heading\nL21:\nL22:Rule", (20, ["Heading", "", "Rule"])),
        ([1, 2], "L1:one\r\nL2:two\r\n", (1, ["one", "two"])),
        ([1, 2], "one\r\ntwo\r\n", (1, ["one", "two"])),
    ],
)
def test_visible_ranges_preserve_blanks_and_numbered_short_outputs(requested, text, actual):
    assert visible_lines(text, *requested) == actual


@pytest.mark.parametrize(
    "text",
    [
        "L2:a\nL4:b",
        "L2:a\nL2:b",
        "L3:a\nL2:b",
        "L2:a\nunmarked",
        "L2:a\nL3 :b",
        "L1:a\nL2:b",
        "L4:a\nL5:b",
        "L2:a\n[one line omitted]\nL4:b",
        "L2:a\n[truncated]",
    ],
)
def test_ambiguous_numbering_omissions_and_outside_ranges_fail(text):
    assert visible_lines(text, 2, 4) is None


def test_unnumbered_short_view_requires_visible_corroboration(tmp_path):
    path = tmp_path / "source" / "example.al"
    short = events(path, [172, 195], "begin\nend;")
    assert view_records(short, tmp_path) == []
    proof = events(path, [170, 174], "header\n\nbegin\nend;\n", "proof")
    records = view_records(short + proof, tmp_path)
    assert [(r[0], r[2], r[3]) for r in records] == [("proof", 170, ["header", "", "begin", "end;", ""]), ("view", 172, ["begin", "end;"])]
    assert not any(r[0] == "view" for r in view_records(short + events(path, [170, 174], "header\n\nbegin\nother;\n", "proof"), tmp_path))


def resolve(tmp_path, source, span, quote, extra=None):
    raw = {
        "id": "F001",
        "verdict": "supported",
        "trigger": "fixture trigger",
        "call_path_and_guards": "fixture path",
        "impact": "fixture impact",
        "counterevidence": "fixture counterevidence",
        "source_view_status": "available",
        "evidence": [
            {"tree": "source", "file": "example.al", "line_start": span[0], "line_end": span[1], "quote": quote},
            {"tree": "knowledge", "file": "rule.md", "line_start": 1, "line_end": 1, "quote": "Rule"},
        ],
    }
    all_events = source + events(tmp_path / "knowledge" / "rule.md", [1, 1], "Rule", "knowledge") + (extra or [])
    return resolve_evidence(validate_votes(["F001"], [raw]), all_events, tmp_path)[0]


@pytest.mark.parametrize(("actual", "claimed"), [([12, 18], [12, 20]), ([172, 186], [172, 187]), ([293, 308], [293, 310])])
def test_genuinely_wrong_ranges_never_shift_or_gain_lines(tmp_path, actual, claimed):
    text = "\n".join(f"safe line {n}" for n in range(actual[0], actual[1] + 1))
    source = events(tmp_path / "source" / "example.al", [actual[0], claimed[1]], text + "\n" * (claimed[1] - actual[1]))
    result = resolve(tmp_path, source, claimed, text)
    assert result.evidence_resolution == "unresolved"


def test_conflicting_successful_visible_views_cannot_cherry_pick(tmp_path):
    path = tmp_path / "source" / "example.al"
    result = resolve(tmp_path, events(path, [2, 3], "begin\nend;"), [2, 3], "begin\nend;", events(path, [2, 3], "different\nend;", "conflict"))
    assert result.evidence_resolution == "unresolved"


def test_partially_overlapping_conflicting_view_is_ambiguous(tmp_path):
    path = tmp_path / "source" / "example.al"
    result = resolve(tmp_path, events(path, [2, 3], "begin\nend;"), [2, 3], "begin\nend;", events(path, [3, 3], "different;", "overlap"))
    assert result.evidence_resolution == "unresolved"


@pytest.mark.parametrize("marker", ["[truncated]", "Content omitted", "Access denied", "[redacted]", "****", "[one line omitted]"])
def test_partial_or_masked_output_never_supports_a_verdict(tmp_path, marker):
    source = events(tmp_path / "source" / "example.al", [1, 3], f"L1:begin\nL2:{marker}\nL3:end;")
    result = resolve(tmp_path, source, [1, 1], "begin")
    assert result.evidence_resolution in ("unavailable", "redacted")


def test_short_view_does_not_read_disk_or_detailed_content(tmp_path, monkeypatch):
    source = events(tmp_path / "source" / "example.al", [1, 40], "begin\nend;")
    source[1]["data"]["result"]["detailedContent"] = "L1:begin\nL2:end;"
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("Do not read source"))
    assert resolve(tmp_path, source, [1, 2], "begin\nend;").evidence_resolution == "unresolved"


def test_plain_omitted_lines_are_not_contiguous_source(tmp_path):
    source = events(tmp_path / "source" / "example.al", [1, 3], "begin\n...\nend;")
    assert resolve(tmp_path, source, [1, 1], "begin").evidence_resolution == "unavailable"


def test_frozen_edges_are_reused_without_judging(monkeypatch):
    from bcbench.dataset.codereview import CodeReviewEntry
    from tools import review_voting_pilot as pilot

    monkeypatch.setattr(pilot, "judge_verdicts", lambda *a, **k: pytest.fail("Offline analysis cannot judge"))
    entry = CodeReviewEntry(
        instance_id="synthetic__fixture-01",
        repo="microsoft/BCApps",
        base_commit="a" * 40,
        created_at="2026-01-01",
        environment_setup_version="27.0",
        project_paths=[],
        patch="fixture patch",
        expected_comments=[{"file": "example.al", "line_start": 1, "body": "bug", "severity": "high"}],
    )
    comment = entry.expected_comments[0].model_dump(mode="json")
    candidates: list[pilot.Candidate] = [{"id": "F001", "comment": comment}]
    edge = {"gold_bucket": "expected", "gold": comment, "candidate_id": "F001", "match": True}
    result = pilot.score_frozen_edges(entry, candidates, {"A": ["F001"], "B": [], "C": ["F001"]}, [edge])
    assert result["A"]["matched"] == result["C"]["matched"] == 1
    assert result["B"]["missed"] == 1
    with pytest.raises(ValueError, match="Frozen judge edges"):
        pilot.score_frozen_edges(entry, candidates, {"A": ["F001"]}, [edge | {"candidate_id": "wrong"}])
    with pytest.raises(ValueError, match="shorter"):
        pilot.score_frozen_edges(entry, candidates, {"A": ["F001"]}, [])


def test_historical_integrity_verification_rejects_changes(tmp_path):
    from tools.review_voting_evidence import file_digest
    from tools.review_voting_reanalyze import verify_history

    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([]))
    manifest = {"root": str(tmp_path), "artifacts": {path.name: file_digest(path)}}
    verify_history(tmp_path, manifest)
    path.write_text("changed")
    with pytest.raises(ValueError, match="Historical artifact changed"):
        verify_history(tmp_path, manifest)


@pytest.mark.parametrize(
    ("fixture", "requested", "visible", "claim", "quoted", "valid"),
    [
        ("long-knowledge-range", [12, 22], [12, 22], [12, 20], [12, 18], False),
        ("short-source-range", [172, 195], [172, 187], [172, 187], [172, 186], False),
        ("blank-after-article", [10, 23], [10, 23], [20, 22], [20, 22], True),
        ("long-source-range", [286, 313], [286, 313], [293, 310], [293, 308], False),
        ("blank-after-description", [12, 15], [12, 15], [12, 15], [12, 15], True),
        ("blank-after-antipattern", [19, 25], [19, 25], [19, 25], [19, 25], True),
        ("blank-after-other-description", [12, 15], [12, 15], [12, 15], [12, 15], True),
        ("single-description-line", [11, 19], [11, 19], [14, 14], [14, 14], True),
        ("single-practice-line", [11, 19], [11, 19], [18, 18], [18, 18], True),
    ],
)
def test_nine_historical_failure_shapes_without_historical_content(tmp_path, fixture, requested, visible, claim, quoted, valid):
    lines = {n: f"{fixture} line {n}" for n in range(visible[0], visible[1] + 1)}
    lines[visible[1]] = ""
    content = "\n".join(lines.values())
    quote = "\n".join(lines[n] for n in range(quoted[0], quoted[1] + 1))
    source = events(tmp_path / "source" / "example.al", requested, content)
    result = resolve(tmp_path, source, claim, quote)
    assert (result.evidence_resolution == "tool_view_matched") is valid


def test_shared_source_references_cannot_resolve_from_output_or_gold(tmp_path):
    roots = {"source": tmp_path / "prepared", "knowledge": tmp_path / "knowledge"}
    payload = {
        "id": "F001",
        "verdict": "supported",
        "trigger": "fixture",
        "call_path_and_guards": "fixture",
        "impact": "fixture",
        "counterevidence": "fixture",
        "source_view_status": "available",
        "evidence": [
            {"tree": "source", "file": "example.al", "line_start": 1, "line_end": 1, "quote": "Safe code"},
            {"tree": "knowledge", "file": "rule.md", "line_start": 1, "line_end": 1, "quote": "Rule"},
        ],
    }
    work = tmp_path / "voter" / "context"
    allowed = events(roots["source"] / "example.al", [1, 1], "Safe code") + events(roots["knowledge"] / "rule.md", [1, 1], "Rule", "knowledge")
    assert resolve_evidence(validate_votes(["F001"], [payload]), allowed, work, roots=roots)[0].evidence_resolution == "tool_view_matched"
    allowed[0]["data"]["arguments"]["path"] = str(tmp_path / "gold" / "example.al")
    assert resolve_evidence(validate_votes(["F001"], [payload]), allowed, work, roots=roots)[0].evidence_resolution == "unresolved"
