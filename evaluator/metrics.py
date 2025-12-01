from __future__ import annotations


class LlmDuration:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("llm_duration", 0)


class ToolCalls:
    def __call__(self, *, metadata: dict, **kwargs):
        tool_usage: dict[str, int] = metadata.get("tool_usage", {})
        return sum(tool_usage.values()) if tool_usage else 0
