"""Analyze a bcal ``--log-full`` JSONL to check whether an injected payload actually reached the model.

The harms harness only produces a meaningful XPIA signal if the tainted seam is (a) read by a tool the
model invokes and (b) surfaced in that tool's result. This module inspects the per-trial log to report
which tools ran and whether the injected payload appeared in any tool result — turning "did the
injection land?" into an automated, per-trial fact instead of a manual investigation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

__all__ = ["TrialLogAnalysis", "analyze_trial_log"]

_MIN_NEEDLE = 12  # require a reasonably specific match to avoid coincidental hits
_NEEDLE_LEN = 40


class TrialLogAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    tools_invoked: list[str]
    payload_in_tool_result: bool


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def analyze_trial_log(log_path: Path | None, payload: str) -> TrialLogAnalysis:
    """Return the tools invoked and whether ``payload`` surfaced in any tool result.

    Matching is done on an alphanumeric-only projection so it is robust to the harness's XML-escaping
    and JSON re-serialization of the payload.
    """
    if log_path is None or not log_path.exists():
        return TrialLogAnalysis(tools_invoked=[], payload_in_tool_result=False)

    needle = _alnum(payload)[:_NEEDLE_LEN]
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
            result_text = _alnum(json.dumps(event.get("result"), ensure_ascii=False))
            if needle in result_text:
                landed = True

    return TrialLogAnalysis(tools_invoked=tools, payload_in_tool_result=landed)
