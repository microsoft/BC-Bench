"""Build a code-review dataset entry from a real GitHub pull request.

Turns a PR (its diff) plus a set of expected review comments into a CodeReviewEntry.
Two ways to decide which of the PR's inline comments are the *expected* findings:

- ``reviewer``: keep comments authored by a given login (e.g. a human reviewer who
  wrote the gold findings directly on the PR).
- ``reacted``: keep comments that received a positive reaction (thumbs-up / heart
  / ...) from any author; combine with ``reviewer`` to restrict to the review bot.
  Comments with only a thumbs-down are dropped, which turns them into false-positive
  guards by omission (the construct stays in the patch but is absent from
  ``expected_comments``, so flagging it costs precision).

If neither is given, every top-level inline comment on the PR is used.
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


def _comment_line_span(comment: dict[str, Any]) -> tuple[int, int | None] | None:
    """Return (line_start, line_end) for a RIGHT-side comment, or None if unplaceable."""
    if comment.get("in_reply_to_id"):
        return None  # thread reply, not a standalone finding
    if (comment.get("side") or "RIGHT") != "RIGHT":
        return None  # LEFT-side comments reference base lines, not the reviewed diff
    line = comment.get("line")
    if not line:
        return None  # outdated / unanchored: current line no longer exists in the patch
    start = comment.get("start_line")
    if start and start != line:
        return int(start), int(line)
    return int(line), None


def build_expected_comments(
    comments: list[dict[str, Any]],
    *,
    reviewer: str | None,
    reacted: bool,
    reactions_by_id: dict[int, list[dict[str, Any]]] | None = None,
) -> list[ReviewComment]:
    """Select and convert PR inline comments into expected ReviewComments."""
    reactions_by_id = reactions_by_id or {}
    selected: list[ReviewComment] = []

    for comment in comments:
        if reviewer is not None and ((comment.get("user") or {}).get("login") or "").casefold() != reviewer.casefold():
            continue
        if reacted:
            cid = comment.get("id")
            reactions = reactions_by_id.get(cid, []) if cid is not None else []
            contents = {r.get("content") for r in reactions}
            if not (contents & POSITIVE_REACTIONS):
                continue

        span = _comment_line_span(comment)
        if span is None:
            logger.debug("Skipping comment %s (unplaceable / reply / left-side)", comment.get("id"))
            continue

        body = (comment.get("body") or "").strip()
        if not body:
            continue

        domain, severity = parse_domain_severity(body)
        selected.append(
            ReviewComment(
                file=comment["path"],
                line_start=span[0],
                line_end=span[1],
                body=body,
                domain=domain,
                severity=severity,
            )
        )

    return selected


def _build_codereview_entry(
    gh_client: GHClient,
    pr_number: int,
    repo: str,
    environment_setup_version: str,
    reviewer: str | None,
    reacted: bool,
    area: str | None,
) -> CodeReviewEntry:
    logger.info("Collecting code-review entry for PR #%s from %s", pr_number, repo)

    pr_data: dict[str, Any] = gh_client.get_pr_info(pr_number)
    base_ref = pr_data.get("baseRefOid", "")
    head_ref = pr_data.get("headRefOid", "")
    if not base_ref or not head_ref:
        raise CollectionError("Unable to determine base/head commit from PR data")

    base_commit = gh_client.get_merge_base(base_ref, head_ref)
    if not base_commit:
        raise CollectionError("Unable to determine merge-base commit for PR")

    patch = gh_client.get_pr_diff(pr_number)
    if not patch.strip():
        raise CollectionError("PR diff is empty")

    comments = gh_client.get_pr_review_comments(pr_number)
    reactions_by_id: dict[int, list[dict[str, Any]]] = {}
    if reacted:
        for comment in comments:
            cid = comment.get("id")
            if cid is None:
                continue
            # Only spend a reactions API call on comments that can actually become a
            # finding: skip other reviewers, replies, LEFT-side/unplaceable and empty
            # bodies (build_expected_comments applies the same filters again).
            if reviewer is not None and ((comment.get("user") or {}).get("login") or "").casefold() != reviewer.casefold():
                continue
            if _comment_line_span(comment) is None:
                continue
            if not (comment.get("body") or "").strip():
                continue
            reactions_by_id[cid] = gh_client.get_review_comment_reactions(cid)

    expected_comments = build_expected_comments(comments, reviewer=reviewer, reacted=reacted, reactions_by_id=reactions_by_id)
    logger.info("Selected %d expected comment(s) from %d PR comment(s)", len(expected_comments), len(comments))

    return CodeReviewEntry(
        repo=repo,
        instance_id=f"{repo.replace('/', '__')}-{pr_number}",
        base_commit=base_commit,
        created_at=pr_data.get("createdAt", ""),
        environment_setup_version=environment_setup_version,
        patch=patch,
        metadata=EntryMetadata(area=area),
        expected_comments=expected_comments,
    )


def collect_codereview_entry(
    pr_number: int,
    output: Path,
    environment_setup_version: str,
    repo: str = "microsoft/BCApps",
    reviewer: str | None = None,
    reacted: bool = False,
    area: str | None = None,
) -> CodeReviewEntry:
    gh_client = GHClient(repo)

    try:
        entry = _build_codereview_entry(gh_client, pr_number, repo, environment_setup_version, reviewer, reacted, area)
    except CollectionError:
        raise
    except Exception as exc:
        raise CollectionError(f"Failed to collect code-review entry for PR #{pr_number}: {exc}") from exc

    try:
        entry.save_to_file(output)
    except OSError as exc:
        raise CollectionError(f"Failed to write dataset entry to {output}: {exc}") from exc

    logger.info("Saved code-review entry %s to %s", entry.instance_id, output)
    return entry
