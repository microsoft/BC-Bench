"""Pure, testable core for the context-free file-path identification task.

No I/O or model invocation lives here — see ``runner.py`` for that. Everything
in this module is a pure function of its inputs so it can be unit-tested without
a network, a container, or a CLI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import PurePosixPath
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.dataset import BaseDatasetEntry

__all__ = [
    "FilePathIdentificationResult",
    "FilePathIdentificationScore",
    "IdentificationAggregate",
    "aggregate_results",
    "build_identification_prompt",
    "extract_gold_files",
    "normalize_path",
    "parse_prediction",
    "score_prediction",
    "split_by_cutoff",
]


def normalize_path(path: str) -> str:
    cleaned = path.strip().strip("`\"'").replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    return cleaned.strip("/")


def _basename(path: str) -> str:
    normalized = normalize_path(path)
    return PurePosixPath(normalized).name.lower() if normalized else ""


def extract_gold_files(patch: str) -> list[str]:
    """Repo-relative paths a fix patch modifies — the ground-truth buggy files."""
    gold: list[str] = []
    for raw in extract_file_paths_from_patch(patch):
        normalized = normalize_path(raw)
        if normalized and normalized not in gold:
            gold.append(normalized)
    return gold


def build_identification_prompt(task: str, top_k: int, repo: str = "microsoft/BCApps") -> str:
    # NOTE: ``task`` is interpolated as a value, so any braces in the AL bug report stay literal.
    return (
        f'You are analyzing a bug report from the Business Central (AL) repository "{repo}".\n\n'
        f"You do NOT have access to the repository source code. Based ONLY on the bug report below, "
        f"identify the {top_k} repository-relative file path(s) most likely to contain the code that must be "
        f"changed to fix this bug, ordered from most to least likely.\n\n"
        f"Business Central AL source files follow the convention <ObjectName>.<ObjectType>.al "
        f"(for example SalesHeader.Table.al, SalesOrder.Page.al, SalesPost.Codeunit.al).\n\n"
        f"Answer only from the bug report text. Respond with ONLY a JSON array of at most {top_k} path "
        f'strings, for example ["src/App/Foo.Table.al", "src/App/Bar.Codeunit.al"]. Do not add any prose.\n\n'
        f"Bug report:\n{task}"
    )


def _extract_json_array(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "[]"
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _candidate_path(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        mapping = cast(dict[str, object], item)
        for key in ("path", "file", "file_path", "filepath"):
            value = mapping.get(key)
            if isinstance(value, str):
                return value
    return None


def parse_prediction(raw_text: str, top_k: int | None = None) -> list[str]:
    try:
        data = json.loads(_extract_json_array(raw_text))
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    paths: list[str] = []
    for item in data:
        candidate = _candidate_path(item)
        if candidate is None:
            continue
        normalized = normalize_path(candidate)
        if normalized and normalized not in paths:
            paths.append(normalized)

    return paths[:top_k] if top_k is not None else paths


class FilePathIdentificationScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    exact_hit: bool
    basename_hit: bool
    exact_recall: float
    basename_recall: float


def score_prediction(predicted: list[str], gold: list[str]) -> FilePathIdentificationScore:
    """Score predicted paths against gold buggy files.

    Reports two granularities: exact repo-relative path match (strict, needs
    knowledge of the repo layout) and basename match (the AL object file name,
    which is the real memorization signal).
    """
    gold_paths = {normalize_path(p) for p in gold if normalize_path(p)}
    pred_paths = {normalize_path(p) for p in predicted if normalize_path(p)}
    gold_names = {_basename(p) for p in gold if _basename(p)}
    pred_names = {_basename(p) for p in predicted if _basename(p)}

    exact_matched = gold_paths & pred_paths
    name_matched = gold_names & pred_names

    return FilePathIdentificationScore(
        exact_hit=bool(exact_matched),
        basename_hit=bool(name_matched),
        exact_recall=len(exact_matched) / len(gold_paths) if gold_paths else 0.0,
        basename_recall=len(name_matched) / len(gold_names) if gold_names else 0.0,
    )


class FilePathIdentificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    instance_id: str
    model: str
    category: str
    created_at: str
    area: str | None = None
    top_k: int
    gold_files: list[str]
    predicted_files: list[str]
    score: FilePathIdentificationScore
    raw_output: str = ""
    error: str | None = None

    @classmethod
    def build(
        cls,
        *,
        entry: BaseDatasetEntry,
        model: str,
        category: str,
        top_k: int,
        predicted_files: list[str],
        raw_output: str = "",
        error: str | None = None,
    ) -> FilePathIdentificationResult:
        gold = extract_gold_files(entry.patch)
        return cls(
            instance_id=entry.instance_id,
            model=model,
            category=category,
            created_at=entry.created_at,
            area=entry.metadata.area,
            top_k=top_k,
            gold_files=gold,
            predicted_files=predicted_files,
            score=score_prediction(predicted_files, gold),
            raw_output=raw_output,
            error=error,
        )


class IdentificationAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    count: int = Field(description="Total results in this group, including errored ones")
    scored: int = Field(description="Results that ran successfully and were scored")
    error_count: int
    exact_hit_rate: float
    basename_hit_rate: float
    mean_exact_recall: float
    mean_basename_recall: float


def aggregate_results(results: list[FilePathIdentificationResult], label: str = "all") -> IdentificationAggregate:
    scored = [r for r in results if r.error is None]
    n = len(scored)

    def rate(predicate: Callable[[FilePathIdentificationResult], bool]) -> float:
        return sum(1 for r in scored if predicate(r)) / n if n else 0.0

    def mean(selector: Callable[[FilePathIdentificationResult], float]) -> float:
        return sum(selector(r) for r in scored) / n if n else 0.0

    return IdentificationAggregate(
        label=label,
        count=len(results),
        scored=n,
        error_count=sum(1 for r in results if r.error is not None),
        exact_hit_rate=rate(lambda r: r.score.exact_hit),
        basename_hit_rate=rate(lambda r: r.score.basename_hit),
        mean_exact_recall=mean(lambda r: r.score.exact_recall),
        mean_basename_recall=mean(lambda r: r.score.basename_recall),
    )


def split_by_cutoff(results: list[FilePathIdentificationResult], cutoff: str) -> tuple[list[FilePathIdentificationResult], list[FilePathIdentificationResult]]:
    """Split results into (pre-cutoff, on-or-after-cutoff) by ``created_at``.

    Pre-cutoff entries were public before the boundary (potentially in training
    data); on/after-cutoff entries act as the clean control. Entries with an
    unparseable date are conservatively grouped with the pre-cutoff set.
    """
    boundary = date.fromisoformat(cutoff)
    pre: list[FilePathIdentificationResult] = []
    post: list[FilePathIdentificationResult] = []
    for result in results:
        try:
            created = date.fromisoformat(result.created_at[:10])
        except ValueError:
            pre.append(result)
            continue
        (post if created >= boundary else pre).append(result)
    return pre, post
