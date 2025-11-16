from __future__ import annotations


class ResolutionRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("resolved", False)


class BuildRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("build", False)
