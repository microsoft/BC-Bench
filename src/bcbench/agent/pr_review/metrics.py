import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from bcbench.exceptions import AgentError
from bcbench.types import AgentMetrics

FILTER_REPORT_FILE_NAME = "_filter-report.json"
_KNOWLEDGE_LAYERS = {"microsoft", "community", "custom"}


class _FilterRemoval(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: Literal["knowledge", "skill"]


class _FilterReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    removed: list[_FilterRemoval]


def _load_filter_report(path: Path) -> _FilterReport:
    if not path.exists():
        raise AgentError(f"BCQuality filter report not found at {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read BCQuality filter report {path}: {exc}") from exc
    try:
        return _FilterReport.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"BCQuality filter report {path} has an invalid shape: {exc}") from exc


def _count_available_knowledge(bcquality_root: Path) -> int:
    def is_knowledge_file(path: Path) -> bool:
        parts = path.relative_to(bcquality_root).parts
        return len(parts) >= 3 and parts[0].lower() in _KNOWLEDGE_LAYERS and parts[1].lower() == "knowledge"

    return sum(1 for path in bcquality_root.rglob("*.md") if path.is_file() and is_knowledge_file(path))


def build_pr_review_metrics(bcquality_root: Path, execution_time: float) -> AgentMetrics:
    report = _load_filter_report(bcquality_root / FILTER_REPORT_FILE_NAME)
    return AgentMetrics(
        execution_time=execution_time,
        knowledge_files=_count_available_knowledge(bcquality_root),
        knowledge_pruned=sum(1 for item in report.removed if item.kind == "knowledge"),
    )
