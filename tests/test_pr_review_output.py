import json

from bcbench.agent.pr_review.review_output import engine_report_to_review_comments, load_engine_report
from bcbench.evaluate.review_parsing import parse_review_output


def _report(findings: list[dict]) -> dict:
    return {"outcome": "completed", "outcome-reason": "", "findings": findings}


def test_load_engine_report_parses_object() -> None:
    report = load_engine_report(json.dumps(_report([])))
    assert report is not None
    assert report["findings"] == []


def test_load_engine_report_rejects_empty_or_invalid() -> None:
    assert load_engine_report("") is None
    assert load_engine_report("   ") is None
    assert load_engine_report("not json") is None
    # A bare JSON array is not the engine report shape.
    assert load_engine_report("[]") is None


def test_maps_production_normalized_finding() -> None:
    report = _report(
        [
            {
                "severity": "High",
                "filePath": "src/Foo.al",
                "lineNumber": 42,
                "issue": "Missing ToolTip on field.",
                "domain": "ui",
            }
        ]
    )
    comments = engine_report_to_review_comments(report)
    assert comments == [
        {
            "file": "src/Foo.al",
            "line_start": 42,
            "line_end": 42,
            "severity": "high",
            "domain": "ui",
            "body": "Missing ToolTip on field.",
        }
    ]


def test_normalizes_path_and_lowercases_severity() -> None:
    report = _report(
        [
            {
                "severity": "CRITICAL",
                "filePath": ".\\src\\Bar.al",
                "lineNumber": 7,
                "issue": "Unchecked Get.",
                "domain": "error-handling",
            }
        ]
    )
    (comment,) = engine_report_to_review_comments(report)
    assert comment["file"] == "src/Bar.al"
    assert comment["severity"] == "critical"


def test_includes_issue_and_recommendation_in_body() -> None:
    report = _report(
        [
            {"filePath": "a.al", "lineNumber": 1, "issue": "issue text", "recommendation": "rec text"},
            {"filePath": "b.al", "lineNumber": 2, "recommendation": "rec only"},
        ]
    )
    comments = engine_report_to_review_comments(report)
    assert [c["body"] for c in comments] == ["issue text\n\nRecommendation: rec text", "rec only"]


def test_drops_findings_missing_file_line_or_body() -> None:
    report = _report(
        [
            {"lineNumber": 5, "issue": "no file"},
            {"filePath": "c.al", "issue": "no line"},
            {"filePath": "d.al", "lineNumber": 0, "issue": "non-positive line"},
            {"filePath": "e.al", "lineNumber": 3, "issue": "   "},
            {"filePath": "f.al", "lineNumber": 3},
        ]
    )
    assert engine_report_to_review_comments(report) == []


def test_missing_or_non_list_findings_yields_empty() -> None:
    assert engine_report_to_review_comments({"outcome": "completed"}) == []
    assert engine_report_to_review_comments({"findings": None}) == []
    assert engine_report_to_review_comments({"findings": "nope"}) == []


def test_output_is_consumable_by_review_parser() -> None:
    report = _report(
        [
            {
                "severity": "Medium",
                "filePath": "src/Baz.al",
                "lineNumber": 10,
                "issue": "Some finding.",
                "domain": "performance",
            }
        ]
    )
    comments = engine_report_to_review_comments(report)
    parsed = parse_review_output(json.dumps(comments))
    assert parsed is not None
    assert len(parsed) == 1
    assert parsed[0].file == "src/Baz.al"
    assert parsed[0].line_start == 10
    assert parsed[0].body == "Some finding."
