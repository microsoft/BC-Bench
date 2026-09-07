from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bcbench.types import PlaybookMode

__all__ = [
    "PlaybookDefinition",
    "PlaybookManifest",
    "load_playbook_manifest",
    "playbook_revision",
    "resolve_playbook_for_area",
    "resolve_playbook_for_paths",
]


class PlaybookDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$")]
    file: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*\.md$")]
    areas: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    paths: Annotated[list[str], Field(min_length=1)]


class PlaybookManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    playbooks: Annotated[list[PlaybookDefinition], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_uniqueness(self) -> PlaybookManifest:
        ids = [playbook.id for playbook in self.playbooks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate playbook id")

        aliases = [area.casefold() for playbook in self.playbooks for area in playbook.areas]
        if len(aliases) != len(set(aliases)):
            raise ValueError("duplicate area alias")

        roots = [(playbook.id, _path_root(pattern)) for playbook in self.playbooks for pattern in playbook.paths]
        for index, (left_id, left_root) in enumerate(roots):
            for right_id, right_root in roots[index + 1 :]:
                if left_id != right_id and (left_root == right_root or left_root.startswith(f"{right_root}/") or right_root.startswith(f"{left_root}/")):
                    raise ValueError(f"overlapping playbook paths: {left_id} and {right_id}")
        return self


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/").casefold()


def _path_root(pattern: str) -> str:
    normalized = _normalize_path(pattern)
    if not normalized.endswith("/**"):
        raise ValueError(f"playbook path must end with '/**': {pattern}")
    return normalized.removesuffix("/**")


def load_playbook_manifest(playbook_dir: Path) -> PlaybookManifest:
    payload = yaml.safe_load((playbook_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest = PlaybookManifest.model_validate(payload)
    for playbook in manifest.playbooks:
        if not (playbook_dir / playbook.file).is_file():
            raise ValueError(f"missing playbook file: {playbook.file}")
    return manifest


def resolve_playbook_for_area(manifest: PlaybookManifest, area: str | None) -> PlaybookDefinition | None:
    if not area:
        return None

    normalized = area.casefold()
    return next(
        (playbook for playbook in manifest.playbooks if normalized in {alias.casefold() for alias in playbook.areas}),
        None,
    )


def resolve_playbook_for_paths(manifest: PlaybookManifest, paths: list[str]) -> PlaybookDefinition | None:
    matches = {
        playbook.id: playbook for path in paths for playbook in manifest.playbooks if any(PurePosixPath(_normalize_path(path)).full_match(_normalize_path(pattern)) for pattern in playbook.paths)
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def playbook_revision(playbook_dir: Path, manifest: PlaybookManifest) -> str:
    digest = hashlib.sha256()
    paths = [
        playbook_dir / "manifest.yaml",
        *(playbook_dir / playbook.file for playbook in sorted(manifest.playbooks, key=lambda item: item.id)),
    ]
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
