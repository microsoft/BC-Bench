"""Build code-review dataset entries from a real GitHub pull request.

A PR is turned into one entry **per reviewed commit** (the per-commit contract, not
per-PR): every inline review comment is anchored to the commit it was written on
(``original_commit_id``) and the line it referenced then (``original_line``). The
entry for a commit stores the diff the reviewer actually saw at that point - the
three-dot range ``base...original_commit_id`` - so the expected findings line up with
the patch the agent is scored against, instead of being re-anchored onto the full
final PR diff. Comments spread across N distinct commits therefore produce N entries;
a PR reviewed in a single pass (the common case) still produces exactly one entry,
and when that pass is the PR head the entry is byte-identical to the old per-PR one.

Two ways to decide which of the PR's inline comments are the *expected* findings:

- ``reviewer``: keep comments authored by a given login (e.g. a human reviewer who
  wrote the gold findings directly on the PR).
- ``reacted``: keep comments that received a positive reaction (thumbs-up / heart
  / ...) from any author; combine with ``reviewer`` to restrict to the review bot.
  Comments with only a thumbs-down are dropped, which turns them into false-positive
  guards by omission (the construct stays in the patch but is absent from
  ``expected_comments``, so flagging it costs precision).

If neither is given, every top-level inline comment on the PR is used. If no comment
is selected at all, a single per-PR entry carrying the full final diff and no expected
comments is emitted as a backward-compatible fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bcbench.collection.gh_client import GHClient
from bcbench.dataset import CodeReviewEntry, ReviewComment, Severity
from bcbench.dataset.dataset_entry import EntryMetadata
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)

# GitHub reaction contents that mark a comment as a confirmed (good) finding.
POSITIVE_REACTIONS = frozenset({"+1", "heart", "hooray", "rocket"})

_SEVERITY_WORDS = ("critical", "high", "medium", "low", "error", "warning", "suggestion", "info", "major", "minor")
# Words the ReviewComment severity enum doesn't know, mapped to ones it does.
_SEVERITY_WORD_ALIASES = {"major": "high", "minor": "low"}


def parse_domain_severity(body: str) -> tuple[str | None, Severity | None]:
    """Best-effort extraction of (domain, severity) from a review-comment body.

    Recognises both the reviewer-bot header (``... Medium Severity - Performance ...``)
    and the ``**Domain - title** _(major)_`` shape humans write. Both fields are
    optional on ReviewComment, so anything unparsed simply stays ``None``.
    """
    import re

    domain: str | None = None
    # Preferred: the explicit metadata marker the review bot appends. It survives
    # LaTeX-escaped headers (e.g. "Severity\ \u2014\ Performance") that the header
    # regex below cannot read.
    marker = re.search(r"<!--\s*agent_domain:\s*([A-Za-z][\w /-]*?)\s*-->", body)
    if marker:
        domain = marker.group(1).strip()
    else:
        # Bot header: "<severity> Severity - <Domain>"
        match = re.search(r"Severity\s*[\u2014-]\s*([A-Za-z][A-Za-z /]+)", body)
        if match:
            domain = match.group(1).strip()
        else:
            # Human header: leading "**<Domain> - ...**"
            match = re.match(r"\s*\*\*\s*([A-Za-z][A-Za-z ]+?)\s*[\u2014-]", body)
            if match:
                domain = match.group(1).strip()

    severity: Severity | None = None
    words = "|".join(_SEVERITY_WORDS)
    # Prefer an explicit annotation over a bare severity-like word that may appear in
    # prose (e.g. "high" inside "high-impact" in a title). Order: an explicit "(minor)"
    # tag, then the bot "<severity> Severity" header, then a broad first-word fallback.
    sev_match = (
        re.search(r"\(\s*(" + words + r")\s*\)", body, re.IGNORECASE) or re.search(r"\b(" + words + r")\s+severity\b", body, re.IGNORECASE) or re.search(r"\b(" + words + r")\b", body, re.IGNORECASE)
    )
    if sev_match:
        word = sev_match.group(1).lower()
        word = _SEVERITY_WORD_ALIASES.get(word, word)
        try:
            severity = Severity.from_input(word)
        except ValueError:
            severity = None

    return domain, severity


def _comment_line_span(comment: dict[str, Any], *, use_original: bool = False) -> tuple[int, int | None] | None:
    """Return (line_start, line_end) for a RIGHT-side comment, or None if unplaceable.

    With ``use_original`` the span is read from ``original_line`` / ``original_start_line``
    (the comment's position in the diff of the commit it was written on) instead of the
    live ``line`` / ``start_line`` (its position in the current head diff).
    """
    if comment.get("in_reply_to_id"):
        return None  # thread reply, not a standalone finding
    if (comment.get("side") or "RIGHT") != "RIGHT":
        return None  # LEFT-side comments reference base lines, not the reviewed diff
    line_key, start_key = ("original_line", "original_start_line") if use_original else ("line", "start_line")
    line = comment.get(line_key)
    if not line:
        return None  # outdated / unanchored: the line no longer exists in the target diff
    start = comment.get(start_key)
    if start and start != line:
        return int(start), int(line)
    return int(line), None


def _select_comment(
    comment: dict[str, Any],
    *,
    reviewer: str | None,
    reacted: bool,
    reactions_by_id: dict[int, list[dict[str, Any]]],
    use_original: bool,
) -> ReviewComment | None:
    """Apply the reviewer/reacted/placeable filters and convert to a ReviewComment.

    Returns None when the comment is filtered out or cannot be placed on the target
    diff. ``use_original`` selects which side of the comment's position pair to anchor
    to (see _comment_line_span).
    """
    if reviewer is not None and ((comment.get("user") or {}).get("login") or "").casefold() != reviewer.casefold():
        return None
    if reacted:
        cid = comment.get("id")
        reactions = reactions_by_id.get(cid, []) if cid is not None else []
        contents = {r.get("content") for r in reactions}
        if not (contents & POSITIVE_REACTIONS):
            return None

    span = _comment_line_span(comment, use_original=use_original)
    if span is None:
        logger.debug("Skipping comment %s (unplaceable / reply / left-side)", comment.get("id"))
        return None

    body = (comment.get("body") or "").strip()
    if not body:
        return None

    domain, severity = parse_domain_severity(body)
    return ReviewComment(
        file=comment["path"],
        line_start=span[0],
        line_end=span[1],
        body=body,
        domain=domain,
        severity=severity,
    )


def build_expected_comments(
    comments: list[dict[str, Any]],
    *,
    reviewer: str | None,
    reacted: bool,
    reactions_by_id: dict[int, list[dict[str, Any]]] | None = None,
) -> list[ReviewComment]:
    """Select PR inline comments and convert them using their head positions (per-PR)."""
    reactions_by_id = reactions_by_id or {}
    selected: list[ReviewComment] = []
    for comment in comments:
        review_comment = _select_comment(comment, reviewer=reviewer, reacted=reacted, reactions_by_id=reactions_by_id, use_original=False)
        if review_comment is not None:
            selected.append(review_comment)
    return selected


def group_expected_by_commit(
    comments: list[dict[str, Any]],
    *,
    reviewer: str | None,
    reacted: bool,
    fallback_commit: str,
    reactions_by_id: dict[int, list[dict[str, Any]]] | None = None,
) -> list[tuple[str, list[ReviewComment]]]:
    """Group selected comments by the commit they were written on (per-commit contract).

    Each comment is anchored to ``original_commit_id`` (falling back to ``commit_id``
    then ``fallback_commit``) and its ``original_line`` position. Groups are returned in
    first-appearance order so per-commit entry numbering is stable across runs.
    """
    reactions_by_id = reactions_by_id or {}
    groups: dict[str, list[ReviewComment]] = {}
    order: list[str] = []
    for comment in comments:
        review_comment = _select_comment(comment, reviewer=reviewer, reacted=reacted, reactions_by_id=reactions_by_id, use_original=True)
        if review_comment is None:
            continue
        commit = comment.get("original_commit_id") or comment.get("commit_id") or fallback_commit
        if commit not in groups:
            groups[commit] = []
            order.append(commit)
        groups[commit].append(review_comment)
    return [(commit, groups[commit]) for commit in order]


def _make_entry(
    gh_client: GHClient,
    *,
    repo: str,
    instance_id: str,
    base_ref: str,
    head_ref: str,
    commit: str,
    pr_number: int,
    created_at: str,
    environment_setup_version: str,
    area: str | None,
    expected_comments: list[ReviewComment],
) -> CodeReviewEntry:
    """Resolve the base commit + diff the reviewer saw for ``commit`` and build the entry."""
    base_commit = gh_client.get_merge_base(base_ref, commit)
    if not base_commit:
        raise CollectionError(f"Unable to determine merge-base commit for {commit}")
    # For the PR head the cumulative diff is exactly `gh pr diff`; for an earlier
    # reviewed commit, reconstruct base...commit (what GitHub rendered at the time).
    patch = gh_client.get_pr_diff(pr_number) if commit == head_ref else gh_client.get_compare_diff(base_ref, commit)
    if not patch.strip():
        raise CollectionError(f"Diff for commit {commit} is empty")

    return CodeReviewEntry(
        repo=repo,
        instance_id=instance_id,
        base_commit=base_commit,
        created_at=created_at,
        environment_setup_version=environment_setup_version,
        patch=patch,
        metadata=EntryMetadata(area=area),
        expected_comments=expected_comments,
    )


def _build_codereview_entries(
    gh_client: GHClient,
    pr_number: int,
    repo: str,
    environment_setup_version: str,
    reviewer: str | None,
    reacted: bool,
    area: str | None,
) -> list[CodeReviewEntry]:
    logger.info("Collecting code-review entries for PR #%s from %s", pr_number, repo)

    pr_data: dict[str, Any] = gh_client.get_pr_info(pr_number)
    base_ref = pr_data.get("baseRefOid", "")
    head_ref = pr_data.get("headRefOid", "")
    if not base_ref or not head_ref:
        raise CollectionError("Unable to determine base/head commit from PR data")
    created_at = pr_data.get("createdAt", "")

    comments = gh_client.get_pr_review_comments(pr_number)
    reactions_by_id: dict[int, list[dict[str, Any]]] = {}
    if reacted:
        for comment in comments:
            cid = comment.get("id")
            if cid is None:
                continue
            # Only spend a reactions API call on comments that can actually become a
            # finding: skip other reviewers, replies, LEFT-side/unplaceable and empty
            # bodies (group_expected_by_commit applies the same filters again).
            if reviewer is not None and ((comment.get("user") or {}).get("login") or "").casefold() != reviewer.casefold():
                continue
            if _comment_line_span(comment, use_original=True) is None:
                continue
            if not (comment.get("body") or "").strip():
                continue
            reactions_by_id[cid] = gh_client.get_review_comment_reactions(cid)

    groups = group_expected_by_commit(comments, reviewer=reviewer, reacted=reacted, fallback_commit=head_ref, reactions_by_id=reactions_by_id)
    base_instance_id = f"{repo.replace('/', '__')}-{pr_number}"

    if not groups:
        # No comment selected: emit one per-PR entry with the full final diff. This is
        # the backward-compatible fallback and also covers the all-thumbs-down case.
        entry = _make_entry(
            gh_client,
            repo=repo,
            instance_id=base_instance_id,
            base_ref=base_ref,
            head_ref=head_ref,
            commit=head_ref,
            pr_number=pr_number,
            created_at=created_at,
            environment_setup_version=environment_setup_version,
            area=area,
            expected_comments=[],
        )
        logger.info("No expected comments selected; wrote 1 per-PR entry for PR #%s", pr_number)
        return [entry]

    # Suffix the instance id only when a PR splits into more than one reviewed commit,
    # so single-pass PRs keep the stable `<repo>-<pr>` id.
    numbered = len(groups) > 1
    entries: list[CodeReviewEntry] = []
    for index, (commit, review_comments) in enumerate(groups, start=1):
        instance_id = f"{base_instance_id}-{index}" if numbered else base_instance_id
        entries.append(
            _make_entry(
                gh_client,
                repo=repo,
                instance_id=instance_id,
                base_ref=base_ref,
                head_ref=head_ref,
                commit=commit,
                pr_number=pr_number,
                created_at=created_at,
                environment_setup_version=environment_setup_version,
                area=area,
                expected_comments=review_comments,
            )
        )

    logger.info(
        "Built %d code-review entr%s from %d comment(s) for PR #%s",
        len(entries),
        "y" if len(entries) == 1 else "ies",
        len(comments),
        pr_number,
    )
    return entries


def collect_codereview_entries(
    pr_number: int,
    output: Path,
    environment_setup_version: str,
    repo: str = "microsoft/BCApps",
    reviewer: str | None = None,
    reacted: bool = False,
    area: str | None = None,
) -> list[CodeReviewEntry]:
    gh_client = GHClient(repo)

    try:
        entries = _build_codereview_entries(gh_client, pr_number, repo, environment_setup_version, reviewer, reacted, area)
    except CollectionError:
        raise
    except Exception as exc:
        raise CollectionError(f"Failed to collect code-review entries for PR #{pr_number}: {exc}") from exc

    for entry in entries:
        try:
            entry.save_to_file(output)
        except OSError as exc:
            raise CollectionError(f"Failed to write dataset entry to {output}: {exc}") from exc

    logger.info("Saved %d code-review entr%s for PR #%s to %s", len(entries), "y" if len(entries) == 1 else "ies", pr_number, output)
    return entries
