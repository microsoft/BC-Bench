from __future__ import annotations


class ResolutionRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("resolved", False)


class BuildRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("build", False)


class PrePatchFailedRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("pre_patch_failed", False)


class PostPatchPassedRate:
    def __call__(self, *, metadata: dict, **kwargs):
        return metadata.get("post_patch_passed", False)
