"""Analyze a bcal ``--log-full`` JSONL to check whether an injected payload actually reached the model.

The harms harness only produces a meaningful XPIA signal if the tainted seam is (a) read by a tool the
model invokes and (b) surfaced in that tool's result. This module inspects the per-trial log to report
which tools ran and whether the injected payload appeared in any tool result — turning "did the
injection land?" into an automated, per-trial fact instead of a manual investigation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from html import unescape
from pathlib import Path

from pydantic import BaseModel, ConfigDict

__all__ = ["TrialLogAnalysis", "analyze_trial_log"]

_MIN_NEEDLE = 12  # require a reasonably specific match to avoid coincidental hits


class TrialLogAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    tools_invoked: list[str]
    payload_in_tool_result: bool


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unescape(text).lower())


def _result_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return
            yield from _result_strings(decoded)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _result_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _result_strings(item)


def analyze_trial_log(log_path: Path | None, payload: str) -> TrialLogAnalysis:
    """Return the tools invoked and whether ``payload`` surfaced in any tool result.

    Matching is done on an alphanumeric-only projection so it is robust to the harness's XML-escaping
    and JSON re-serialization of the payload.
    """
    if log_path is None or not log_path.exists():
        return TrialLogAnalysis(tools_invoked=[], payload_in_tool_result=False)

    needle = _alnum(payload)
    tools: list[str] = []
    landed = False
    for raw in log_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        kind = event.get("event")
        if kind == "tool_call":
            if name := event.get("tool_name"):
                tools.append(str(name))
        elif kind == "tool_result" and not landed and len(needle) >= _MIN_NEEDLE:
            landed = any(needle in _alnum(text) for text in _result_strings(event.get("result")))

    return TrialLogAnalysis(tools_invoked=tools, payload_in_tool_result=landed)
