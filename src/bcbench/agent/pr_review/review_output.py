"""Map production-normalized engine findings onto BC-Bench's review.json schema.

The BC-ALAgents engine writes ``al-code-review-findings.json`` after its production
parsing and filtering stages. Each finding is shaped like::

    {
      "filePath": "<repo-relative path>",
      "lineNumber": <int>,
      "severity": "Critical|High|Medium|Low",
      "domain": "<domain>",
      "issue": "<human-readable finding>",
      "recommendation": "<optional guidance>",
      ...
    }

BC-Bench's code-review scorer instead reads ``review.json`` from the repo root as
a flat list of ``{file, line_start, line_end, severity, body}`` objects (see
``bcbench.evaluate.review_parsing.parse_review_output``). This module performs the
one transform between the two so the production engine plugs into the existing
scoring pipeline unchanged.
"""

import json
from pathlib import PurePosixPath
from typing import Any

from bcbench.logger import get_logger

logger = get_logger(__name__)

__all__ = ["engine_report_to_review_comments", "load_engine_report"]


def load_engine_report(raw_output: str) -> dict[str, Any] | None:
    """Parse the engine's normalized findings artifact into a report dict.

    Returns ``None`` when the text is empty or not a JSON object.
    """
    if not raw_output.strip():
        return None
    try:
        report = json.loads(raw_output)
    except json.JSONDecodeError:
        logger.warning("Engine findings artifact is not valid JSON")
        return None
    if not isinstance(report, dict):
        logger.warning(f"Engine report is not a JSON object (got {type(report).__name__})")
        return None
    return report


def _normalize_path(file_value: str) -> str:
    return PurePosixPath(file_value.strip().replace("\\", "/")).as_posix().removeprefix("./")


def engine_report_to_review_comments(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert an engine findings report into review.json comment dicts.

    Findings without a file, a positive line, or body text are dropped — those
    cannot be scored as located comments and mirror what the engine's own
    renderer would skip.
    """
    findings = report.get("findings")
    if not isinstance(findings, list):
        return []

    comments: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue

        file_value = finding.get("filePath")
        line_value = finding.get("lineNumber")
        issue = finding.get("issue")
        recommendation = finding.get("recommendation")
        body_parts = [value.strip() for value in (issue, recommendation) if isinstance(value, str) and value.strip()]
        body = "\n\nRecommendation: ".join(body_parts)

        if not isinstance(file_value, str) or not file_value.strip():
            continue
        if not isinstance(line_value, (int, str)) or isinstance(line_value, bool):
            continue
        try:
            line = int(line_value)
        except (TypeError, ValueError):
            continue
        if line <= 0:
            continue
        if not isinstance(body, str) or not body.strip():
            continue

        severity = finding.get("severity")
        domain = finding.get("domain")

        comments.append(
            {
                "file": _normalize_path(file_value),
                "line_start": line,
                "line_end": line,
                "severity": str(severity).strip().lower() if isinstance(severity, str) and severity.strip() else None,
                "domain": domain.strip() if isinstance(domain, str) and domain.strip() else None,
                "body": body.strip(),
            }
        )

    return comments
