"""Tests for building code-review dataset entries from GitHub PRs."""

from unittest.mock import MagicMock, patch

from bcbench.collection.collect_codereview import (
    build_expected_comments,
    collect_codereview_entry,
    parse_domain_severity,
)
from bcbench.dataset.codereview import CodeReviewEntry


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

    def test_explicit_severity_tag_wins_over_word_in_prose(self):
        # "high" appears only inside "high-impact"; the explicit tag is (minor).
        _, severity = parse_domain_severity("high-impact change _(minor)_")
        assert severity == "low"

    def test_agent_domain_marker_wins_over_latex_escaped_header(self):
        # Real bot comments escape the header (Severity\ \u2014\ Performance), which the
        # header regex cannot read, but always append an agent_domain marker.
        body = (
            "$\\textbf{\U0001f7e1\\ Medium\\ Severity\\ \u2014\\ Performance}$\n"
            "### CheckJobTaskIsPosting calls JobTask.Get without SetLoadFields.\n"
            "<!-- agent_domain: performance -->"
        )
        domain, severity = parse_domain_severity(body)
        assert domain == "performance"
        assert severity == "medium"


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


def _gh_double(comments, *, merge_base="a" * 40):
    gh = MagicMock()
    gh.get_pr_info.return_value = {
        "baseRefOid": "b" * 40,
        "headRefOid": "c" * 40,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    gh.get_merge_base.return_value = merge_base
    gh.get_pr_diff.return_value = (
        "diff --git a/src/Foo.al b/src/Foo.al\n"
        "new file mode 100644\n--- /dev/null\n+++ b/src/Foo.al\n"
        "@@ -0,0 +1 @@\n+codeunit 50000 Foo { }\n"
    )
    gh.get_pr_review_comments.return_value = comments
    gh.get_review_comment_reactions.side_effect = lambda cid: [{"content": "+1"}] if cid == 1 else []
    return gh


class TestCollectCodereviewEntry:
    def test_orchestration_writes_reloadable_entry(self, tmp_path):
        out = tmp_path / "codereview.jsonl"
        gh = _gh_double([_comment(1, "src/Foo.al", login="bot")])
        with patch("bcbench.collection.collect_codereview.GHClient", return_value=gh):
            entry = collect_codereview_entry(
                pr_number=9999,
                output=out,
                environment_setup_version="27.0",
                repo="microsoft/BCApps",
                reviewer="bot",
            )
        gh.get_merge_base.assert_called_once_with("b" * 40, "c" * 40)
        assert entry.base_commit == "a" * 40
        reloaded = CodeReviewEntry.load(out)
        assert len(reloaded) == 1
        assert reloaded[0].instance_id == "microsoft__BCApps-9999"
        assert [c.file for c in reloaded[0].expected_comments] == ["src/Foo.al"]

    def test_reacted_fetches_reactions_only_for_candidates(self, tmp_path):
        out = tmp_path / "codereview.jsonl"
        comments = [
            _comment(1, "src/Ok.al"),  # candidate -> reaction fetched
            _comment(2, "src/Reply.al", reply=99),  # reply -> skipped, no API call
            _comment(3, "src/Left.al", side="LEFT"),  # left side -> skipped, no API call
        ]
        gh = _gh_double(comments)
        with patch("bcbench.collection.collect_codereview.GHClient", return_value=gh):
            entry = collect_codereview_entry(
                pr_number=1,
                output=out,
                environment_setup_version="27.0",
                reacted=True,
            )
        fetched = [call.args[0] for call in gh.get_review_comment_reactions.call_args_list]
        assert fetched == [1]  # only the placeable candidate, not the reply / left-side
        assert [c.file for c in entry.expected_comments] == ["src/Ok.al"]
