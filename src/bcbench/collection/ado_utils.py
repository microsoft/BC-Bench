"""Azure DevOps-specific data extraction utilities."""

import re
from html import unescape
from typing import Any

from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def extract_creation_date(pr_data: dict[str, Any]) -> str:
    """Extract creation date from ADO PR data."""
    creation_date = pr_data.get("creationDate", "")
    if creation_date:
        return creation_date[:10]
    raise CollectionError("Creation date not found in PR data.")


def extract_problem_statement(work_item_data: dict[str, Any]) -> tuple[str, str]:
    """Extract problem statement and hints from ADO work item data.

    Returns:
        Tuple of (problem_statement, hints_text).
    """
    fields = work_item_data.get("fields", {})
    if fields.get("System.CommentCount", 0) > 0:
        logger.warning("Work item has comments, additional handling may be required.")

    repro_steps_raw = fields.get("Microsoft.VSTS.TCM.ReproSteps", "")
    logger.debug("Raw repro steps:\n %s", repro_steps_raw)
    repro_steps = _strip_html(repro_steps_raw)

    description_raw = fields.get("System.Description", "")
    logger.debug("Raw description:\n %s", description_raw)
    description = _strip_html(description_raw)

    problem_statement = f"Title: {fields.get('System.Title', '')}\nRepro Steps:\n{repro_steps}\nDescription:\n{description}\n"
    hints = ""

    return problem_statement, hints


def _strip_html(html_text: str) -> str:
    """Strip HTML tags and unescape HTML entities from text."""
    if not html_text:
        return ""
    clean = re.sub(r"<.*?>", "", html_text)
    clean = unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()
