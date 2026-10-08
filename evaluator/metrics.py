from __future__ import annotations

from typing import Any


class BcBenchMetrics:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> dict[str, int]:
        tool_usage: Any = metadata.get("tool_usage", {})
        return {
            "tool_calls": sum(tool_usage.values()) if tool_usage else 0,
            "llm_duration": metadata.pop("llm_duration", 0),
            "TurnCount": metadata.pop("turn_count", 0),
        }
