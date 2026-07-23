"""Tests for building code-review dataset entries from GitHub PRs."""

from bcbench.collection.collect_codereview import (
    build_expected_comments,
    parse_domain_severity,
)


class TestParseDomainSeverity:
    def test_parses_reviewer_bot_header(self):
        body = "$\\textbf{Medium Severity \u2014 Performance}$ SetAutoCalcFields would help here."
        domain, severity = parse_domain_severity(body)
        assert domain == "Performance"
        assert severity == "medium"

    def test_parses_human_header_with_major(self):
        body = "**Privacy \u2014 field-level DataClassification** _(major)_ add DataClassification."
        domain, severity = parse_domain_severity(body)
        assert domain == "Privacy"
        assert severity == "high"  # major -> high

    def test_minor_maps_to_low(self):
        _, severity = parse_domain_severity("**Style \u2014 Locked labels** _(minor)_")
        assert severity == "low"

    def test_unparseable_returns_none(self):
        domain, severity = parse_domain_severity("please take another look at this")
        assert domain is None
        assert severity is None


def _comment(cid, path, *, login="alice", line=10, start_line=None, body="finding", side="RIGHT", reply=None):
    return {
        "id": cid,
        "path": path,
        "user": {"login": login},
        "line": line,
        "start_line": start_line,
        "body": body,
        "side": side,
        "in_reply_to_id": reply,
    }


class TestBuildExpectedComments:
    def test_reviewer_filter_keeps_only_that_author(self):
        comments = [
            _comment(1, "src/A.al", login="wael"),
            _comment(2, "src/B.al", login="bot"),
        ]
        result = build_expected_comments(comments, reviewer="wael", reacted=False)
        assert [c.file for c in result] == ["src/A.al"]

    def test_no_filter_keeps_all_placeable(self):
        comments = [_comment(1, "src/A.al"), _comment(2, "src/B.al")]
        result = build_expected_comments(comments, reviewer=None, reacted=False)
        assert len(result) == 2

    def test_reacted_keeps_positive_drops_thumbs_down(self):
        comments = [_comment(1, "src/Good.al"), _comment(2, "src/Bad.al")]
        reactions = {1: [{"content": "+1"}], 2: [{"content": "-1"}]}
        result = build_expected_comments(comments, reviewer=None, reacted=True, reactions_by_id=reactions)
        assert [c.file for c in result] == ["src/Good.al"]

    def test_reviewer_and_reacted_compose(self):
        comments = [
            _comment(1, "src/A.al", login="bot"),
            _comment(2, "src/B.al", login="bot"),
            _comment(3, "src/C.al", login="human"),
        ]
        reactions = {1: [{"content": "+1"}], 2: [], 3: [{"content": "+1"}]}
        result = build_expected_comments(comments, reviewer="bot", reacted=True, reactions_by_id=reactions)
        assert [c.file for c in result] == ["src/A.al"]

    def test_skips_replies_and_left_side_and_unanchored(self):
        comments = [
            _comment(1, "src/Reply.al", reply=99),
            _comment(2, "src/Left.al", side="LEFT"),
            _comment(3, "src/NoLine.al", line=None),
            _comment(4, "src/Ok.al"),
        ]
        result = build_expected_comments(comments, reviewer=None, reacted=False)
        assert [c.file for c in result] == ["src/Ok.al"]

    def test_multiline_span_sets_start_and_end(self):
        comments = [_comment(1, "src/A.al", line=20, start_line=15)]
        result = build_expected_comments(comments, reviewer=None, reacted=False)
        assert result[0].line_start == 15
        assert result[0].line_end == 20

    def test_path_with_spaces_is_accepted(self):
        comments = [_comment(1, "src/W1/1.Setup Data/Foo.Codeunit.al")]
        result = build_expected_comments(comments, reviewer=None, reacted=False)
        assert result[0].file == "src/W1/1.Setup Data/Foo.Codeunit.al"
