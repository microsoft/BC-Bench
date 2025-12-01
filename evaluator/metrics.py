from __future__ import annotations


class BcBenchMetrics:
    def __call__(self, *, metadata: dict, **kwargs):
        tool_usage: dict[str, int] = metadata.get("tool_usage", {})
        return {
            "llm_duration": metadata.get("llm_duration", 0),
            "tool_calls": sum(tool_usage.values()) if tool_usage else 0,
        }
