from __future__ import annotations


class LlmDuration:
    def __call__(self, *, metadata: dict, **kwargs):
        return {"llm_duration": metadata.pop("llm_duration", 0)}


class ToolCalls:
    def __call__(self, *, metadata: dict, **kwargs):
        tool_usage: dict[str, int] = metadata.get("tool_usage", {})
        return {"tool_calls": sum(tool_usage.values()) if tool_usage else 0}
