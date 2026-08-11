"""Tests for building code-review dataset entries from GitHub PRs."""

from unittest.mock import MagicMock, patch

from bcbench.collection.collect_codereview import (
    collect_codereview_entries,
    group_expected_by_commit,
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
        body = "$\\textbf{\U0001f7e1\\ Medium\\ Severity\\ \u2014\\ Performance}$\n### CheckJobTaskIsPosting calls JobTask.Get without SetLoadFields.\n<!-- agent_domain: performance -->"
        domain, severity = parse_domain_severity(body)
        assert domain == "performance"
        assert severity == "medium"


def _comment(cid, path, *, login="alice", line=10, start_line=None, body="finding", side="RIGHT", reply=None, orig_commit="c" * 40, original_line=None, original_start_line=None):
    # original_line / original_start_line default to the head positions so a comment
    # left on the PR head (the common single-pass case) anchors identically either way.
    return {
        "id": cid,
        "path": path,
        "user": {"login": login},
        "line": line,
        "start_line": start_line,
        "original_line": line if original_line is None else original_line,
        "original_start_line": start_line if original_start_line is None else original_start_line,
        "commit_id": orig_commit,
        "original_commit_id": orig_commit,
        "body": body,
        "side": side,
        "in_reply_to_id": reply,
    }


def _gh_double(comments, *, merge_base="a" * 40):
    gh = MagicMock()
    gh.get_pr_info.return_value = {
        "baseRefOid": "b" * 40,
        "headRefOid": "c" * 40,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    gh.get_merge_base.return_value = merge_base
    gh.get_pr_diff.return_value = "diff --git a/src/Foo.al b/src/Foo.al\nnew file mode 100644\n--- /dev/null\n+++ b/src/Foo.al\n@@ -0,0 +1 @@\n+codeunit 50000 Foo { }\n"
    gh.get_compare_diff.return_value = "diff --git a/src/Bar.al b/src/Bar.al\nnew file mode 100644\n--- /dev/null\n+++ b/src/Bar.al\n@@ -0,0 +1 @@\n+codeunit 50001 Bar { }\n"
    gh.get_pr_review_comments.return_value = comments
    gh.get_review_comment_reactions.side_effect = lambda cid: [{"content": "+1"}] if cid == 1 else []
    return gh


class TestCollectCodereviewEntry:
    def test_orchestration_writes_reloadable_entry(self, tmp_path):
        out = tmp_path / "codereview.jsonl"
        gh = _gh_double([_comment(1, "src/Foo.al", login="bot")])
        with patch("bcbench.collection.collect_codereview.GHClient", return_value=gh):
            entries = collect_codereview_entries(
                pr_number=9999,
                output=out,
                environment_setup_version="27.0",
                repo="microsoft/BCApps",
                reviewer="bot",
            )
        # Single comment on the PR head -> one entry, using the full PR diff.
        gh.get_merge_base.assert_called_once_with("b" * 40, "c" * 40)
        gh.get_compare_diff.assert_not_called()
        assert len(entries) == 1
        assert entries[0].base_commit == "a" * 40
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
            entries = collect_codereview_entries(
                pr_number=1,
                output=out,
                environment_setup_version="27.0",
                reacted=True,
            )
        fetched = [call.args[0] for call in gh.get_review_comment_reactions.call_args_list]
        assert fetched == [1]  # only the placeable candidate, not the reply / left-side
        assert len(entries) == 1
        assert [c.file for c in entries[0].expected_comments] == ["src/Ok.al"]

    def test_per_commit_splits_into_one_entry_per_original_commit(self, tmp_path):
        out = tmp_path / "codereview.jsonl"
        # Two findings written on two different, non-head commits -> two entries, each
        # scoped to the diff of the commit it was reviewed on (get_compare_diff).
        comments = [
            _comment(1, "src/A.al", orig_commit="d" * 40, line=10),
            _comment(2, "src/B.al", orig_commit="e" * 40, line=20),
        ]
        gh = _gh_double(comments)
        with patch("bcbench.collection.collect_codereview.GHClient", return_value=gh):
            entries = collect_codereview_entries(
                pr_number=9999,
                output=out,
                environment_setup_version="27.0",
                repo="microsoft/BCApps",
            )
        assert [e.instance_id for e in entries] == ["microsoft__BCApps-9999-1", "microsoft__BCApps-9999-2"]
        # Non-head commits use the reconstructed compare diff, not the final PR diff.
        gh.get_pr_diff.assert_not_called()
        assert {call.args for call in gh.get_compare_diff.call_args_list} == {("b" * 40, "d" * 40), ("b" * 40, "e" * 40)}
        assert [c.file for e in entries for c in e.expected_comments] == ["src/A.al", "src/B.al"]
        reloaded = CodeReviewEntry.load(out)
        assert len(reloaded) == 2

    def test_no_selected_comments_writes_single_per_pr_entry(self, tmp_path):
        out = tmp_path / "codereview.jsonl"
        # reviewer filter excludes everyone -> fallback: one per-PR entry, full diff, no findings.
        gh = _gh_double([_comment(1, "src/A.al", login="someone-else")])
        with patch("bcbench.collection.collect_codereview.GHClient", return_value=gh):
            entries = collect_codereview_entries(
                pr_number=42,
                output=out,
                environment_setup_version="27.0",
                reviewer="nobody",
            )
        assert len(entries) == 1
        assert entries[0].instance_id == "microsoft__BCApps-42"
        assert entries[0].expected_comments == []
        gh.get_pr_diff.assert_called_once()
        gh.get_compare_diff.assert_not_called()


class TestGroupExpectedByCommit:
    def _files(self, groups):
        return [c.file for _, rcs in groups for c in rcs]

    def test_reviewer_filter_keeps_only_that_author(self):
        comments = [
            _comment(1, "src/A.al", login="wael"),
            _comment(2, "src/B.al", login="bot"),
        ]
        groups = group_expected_by_commit(comments, reviewer="wael", reacted=False, fallback_commit="h" * 40)
        assert self._files(groups) == ["src/A.al"]

    def test_no_filter_keeps_all_placeable(self):
        comments = [_comment(1, "src/A.al"), _comment(2, "src/B.al")]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert self._files(groups) == ["src/A.al", "src/B.al"]

    def test_reacted_keeps_positive_drops_thumbs_down(self):
        comments = [_comment(1, "src/Good.al"), _comment(2, "src/Bad.al")]
        reactions = {1: [{"content": "+1"}], 2: [{"content": "-1"}]}
        groups = group_expected_by_commit(comments, reviewer=None, reacted=True, fallback_commit="h" * 40, reactions_by_id=reactions)
        assert self._files(groups) == ["src/Good.al"]

    def test_reviewer_and_reacted_compose(self):
        comments = [
            _comment(1, "src/A.al", login="bot"),
            _comment(2, "src/B.al", login="bot"),
            _comment(3, "src/C.al", login="human"),
        ]
        reactions = {1: [{"content": "+1"}], 2: [], 3: [{"content": "+1"}]}
        groups = group_expected_by_commit(comments, reviewer="bot", reacted=True, fallback_commit="h" * 40, reactions_by_id=reactions)
        assert self._files(groups) == ["src/A.al"]

    def test_multiline_span_sets_start_and_end(self):
        comments = [_comment(1, "src/A.al", line=20, start_line=15)]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        comment = groups[0][1][0]
        assert comment.line_start == 15
        assert comment.line_end == 20

    def test_path_with_spaces_is_accepted(self):
        comments = [_comment(1, "src/W1/1.Setup Data/Foo.Codeunit.al")]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert groups[0][1][0].file == "src/W1/1.Setup Data/Foo.Codeunit.al"

    def test_groups_by_original_commit_in_first_appearance_order(self):
        comments = [
            _comment(1, "src/A.al", orig_commit="d" * 40),
            _comment(2, "src/B.al", orig_commit="e" * 40),
            _comment(3, "src/C.al", orig_commit="d" * 40),
        ]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert [commit for commit, _ in groups] == ["d" * 40, "e" * 40]
        assert [[c.file for c in rcs] for _, rcs in groups] == [["src/A.al", "src/C.al"], ["src/B.al"]]

    def test_anchors_to_original_line_not_head_line(self):
        # line=99 is the head position; original_line=7 is where it was reviewed.
        comments = [_comment(1, "src/A.al", line=99, original_line=7)]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert groups[0][1][0].line_start == 7

    def test_falls_back_to_commit_id_then_fallback_commit(self):
        no_original = _comment(1, "src/A.al", orig_commit="f" * 40)
        no_original["original_commit_id"] = None  # only commit_id survives
        no_commit = _comment(2, "src/B.al")
        no_commit["original_commit_id"] = None
        no_commit["commit_id"] = None
        groups = group_expected_by_commit([no_original, no_commit], reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert [commit for commit, _ in groups] == ["f" * 40, "h" * 40]

    def test_skips_replies_and_left_side(self):
        comments = [
            _comment(1, "src/Reply.al", reply=99),
            _comment(2, "src/Left.al", side="LEFT"),
            _comment(3, "src/NoLine.al", line=None),
            _comment(4, "src/Ok.al", orig_commit="d" * 40),
        ]
        groups = group_expected_by_commit(comments, reviewer=None, reacted=False, fallback_commit="h" * 40)
        assert [commit for commit, _ in groups] == ["d" * 40]
        assert [c.file for _, rcs in groups for c in rcs] == ["src/Ok.al"]
