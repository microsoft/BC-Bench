from __future__ import annotations


class BcBenchMetrics:
    def __call__(self, *, metadata: dict, **kwargs):
        return {
            "llm_duration": metadata.get("llm_duration", 0),
        }
