import json
import re
from typing import Any

from bcbench.dataset.codereview import ReviewComment, Severity
from bcbench.logger import get_logger

logger = get_logger(__name__)

__all__ = ["parse_review_output"]


def _extract_json_candidate(raw_output: str) -> str:
    stripped = raw_output.strip()
    if not stripped:
        return ""

    if stripped.startswith(("[", "{")):
        return stripped

    block_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_output, re.IGNORECASE)
    if block_match:
        return block_match.group(1).strip()

    generic_block_match = re.search(r"```\s*([\s\S]*?)\s*```", raw_output)
    if generic_block_match:
        return generic_block_match.group(1).strip()

    return stripped


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_comment(item: dict[Any, Any]) -> ReviewComment | None:
    file_path = item.get("file") or item.get("filePath") or item.get("path")
    line_start = _to_int(item.get("line_start") or item.get("lineNumber") or item.get("line"))
    line_end = _to_int(item.get("line_end") or item.get("lineEnd") or item.get("endLine"))
    domain = item.get("domain")
    body = item.get("body") or item.get("issue") or item.get("comment")
    severity = Severity.from_input(str(item.get("severity", "medium")))

    if not isinstance(file_path, str) or not file_path.strip():
        return None
    if line_start is None:
        return None
    if not isinstance(body, str) or not body.strip():
        return None

    try:
        return ReviewComment(
            file=file_path.strip(),
            line_start=line_start,
            line_end=line_end,
            domain=domain.strip() if isinstance(domain, str) and domain.strip() else None,
            body=body.strip(),
            severity=severity,
        )
    except Exception:
        return None


def parse_review_output(raw_output: str) -> list[ReviewComment] | None:
    """Parse raw agent output into review comments.

    Returns ``None`` when the output is not a valid review (empty or unparseable),
    or a (possibly empty) list when it parses — an empty list means the model
    legitimately reported no findings.
    """
    if not raw_output.strip():
        return None

    candidate = _extract_json_candidate(raw_output)
    if not candidate:
        return None

    try:
        raw = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("Failed to parse review output as JSON")
        return None

    raw_items: list[object]
    if isinstance(raw, list):
        raw_items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("findings"), list):
        raw_items = raw["findings"]
    elif isinstance(raw, dict) and any(key in raw for key in ("file", "filePath", "path")):
        raw_items = [raw]
    else:
        logger.warning(f"Expected JSON array or object with findings[], got {type(raw).__name__}")
        return None

    comments: list[ReviewComment] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_comment(item)
        if normalized is not None:
            comments.append(normalized)
        else:
            logger.debug(f"Skipping malformed comment: {item}")

    return comments
