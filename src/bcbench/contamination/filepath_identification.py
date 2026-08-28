"""Pure functions and result models for file-path identification."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from bcbench.types import AgentMetrics, EvaluationCategory


def build_identification_prompt(task: str, repo: str = "microsoft/BCApps") -> str:
    return f"""You will be provided with an issue statement explaining a problem to resolve within a codebase. The code base is: {repo}.
<issue>
{task}
</issue>
You must always include one discussion and one response as part of your response.
Make sure you do not have multiple discussion/response tags.
Please make sure your output precisely matches the following format.
DISCUSSION
Discuss here with yourself about how you came up with this response.
RESPONSE
```
response(s) to the question asked.
```
Now answer the following question:
Given the issue description and project, provide a file-path of the .al file containing the issue relative to the root."""


def parse_prediction(raw_text: str) -> list[str]:
    """Extract the single predicted path from the model's RESPONSE block.

    The answer is taken from the first fenced block after the RESPONSE header,
    so decorated headers, inline fences, and prose after the fence are tolerated.
    Markdown wrappers, path separators, and common diff prefixes are normalized
    on the prediction; gold paths remain unchanged for exact matching.

    Returns:
        A single-item list holding the predicted repository-relative path.

    Raises:
        ValueError: If the model did not answer with exactly one fenced path.
            The probe is new, so unanswerable output should surface loudly
            rather than quietly count as a miss.
    """
    response = re.search(r"(?im)^[ \t]*(?:[*_#>`]+[ \t]*)*RESPONSE[ \t]*:?[ \t]*(?:[*_`]+)?[ \t]*$", raw_text)
    if response is None:
        raise ValueError("Expected the answer in a fenced code block after RESPONSE")

    block = re.search(r"```(?:(?:[A-Za-z0-9_+-]+)?[ \t]*\r?\n)?(.*?)```", raw_text[response.end() :], re.DOTALL)
    if block is None:
        raise ValueError("Expected the answer in a fenced code block after RESPONSE")

    paths = [line.strip() for line in block.group(1).splitlines() if line.strip()]
    if len(paths) != 1:
        raise ValueError(f"Expected exactly one path in the answer block, got {len(paths)}")

    inline_code = re.fullmatch(r"(?P<fence>`+)(?P<path>.+)(?P=fence)", paths[0])
    path = inline_code.group("path").strip() if inline_code else paths[0]
    path = path.strip("\"'").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return [path.strip("/")]


def matches_any_gold_path(predicted_files: list[str], gold_files: list[str]) -> bool:
    """Check whether any predicted path exactly matches a gold path.

    Args:
        predicted_files: Repository-relative paths predicted by the model.
        gold_files: Repository-relative paths modified by the gold patch.

    Returns:
        Whether the two collections contain an identical path.

    Examples:
        >>> matches_any_gold_path(["App/B.al"], ["App/A.al", "App/B.al"])
        True
        >>> matches_any_gold_path(["B.al"], ["App/B.al"])
        False
    """
    # Keep both sides as collections so an all-reference policy can be added later
    # without changing the persisted result shape.
    return bool(set(gold_files) & set(predicted_files))


class FilePathIdentificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    instance_id: str
    model: str
    category: EvaluationCategory
    gold_files: list[str]
    predicted_files: Annotated[list[str], Field(max_length=1)]
    matches_any_gold_path: bool
    metrics: AgentMetrics | None = None
    raw_output: str = ""
