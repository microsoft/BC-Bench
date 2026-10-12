from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

NL2AL_MANIFEST_FILENAME = "nl2al_manifest.json"
NL2AL_PANEL_NAMES = frozenset({"gold", "challenge", "multiturn"})

type NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class NL2ALImportedFrom(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    repository: Literal["microsoft/BC-Bench"]
    ref: NonEmptyString
    commit: CommitSha


class NL2ALPanelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file: NonEmptyString
    count: Annotated[int, Field(ge=0)]
    sha256: Sha256
    evaluation_scope: Literal["single_turn", "final_artifact"]

    @field_validator("file")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        if Path(value).name != value or not value.endswith(".jsonl"):
            raise ValueError("panel file must be a JSONL file name without directories")
        return value


class NL2ALDeferredManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file: NonEmptyString
    count: Annotated[int, Field(ge=0)]
    sha256: Sha256
    evaluation_scope: Literal["deferred"]
    reason: NonEmptyString

    @field_validator("file")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        if Path(value).name != value or not value.endswith(".jsonl"):
            raise ValueError("deferred file must be a JSONL file name without directories")
        return value


class NL2ALManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"]
    version: NonEmptyString
    source_canonical_sha256: Sha256
    status: NonEmptyString
    source_repository: Literal["bic/BC-DeveloperExperience"]
    source_commit: CommitSha
    source_dataset: NonEmptyString
    source_schema_version: NonEmptyString
    imported_from: NL2ALImportedFrom
    generator: NonEmptyString
    panels: dict[str, NL2ALPanelManifest]
    deferred: dict[str, NL2ALDeferredManifest] | None = None

    @model_validator(mode="after")
    def validate_panel_contract(self) -> NL2ALManifest:
        panel_names = set(self.panels)
        if panel_names != NL2AL_PANEL_NAMES:
            missing = sorted(NL2AL_PANEL_NAMES - panel_names)
            unknown = sorted(panel_names - NL2AL_PANEL_NAMES)
            details = [f"missing={missing}" if missing else "", f"unknown={unknown}" if unknown else ""]
            raise ValueError(f"panels must contain exactly {sorted(NL2AL_PANEL_NAMES)} ({', '.join(item for item in details if item)})")

        expected_scopes = {
            "gold": "single_turn",
            "challenge": "single_turn",
            "multiturn": "final_artifact",
        }
        for name, expected_scope in expected_scopes.items():
            if self.panels[name].evaluation_scope != expected_scope:
                raise ValueError(f"panel {name!r} must use evaluation_scope {expected_scope!r}")

        panel_files = [panel.file for panel in self.panels.values()]
        if len(panel_files) != len(set(panel_files)):
            raise ValueError("panel files must be unique")

        deferred_files = [panel.file for panel in (self.deferred or {}).values()]
        if len(deferred_files) != len(set(deferred_files)):
            raise ValueError("deferred files must be unique")
        if set(panel_files).intersection(deferred_files):
            raise ValueError("deferred files must not overlap selectable panel files")
        if any(not name.strip() for name in (self.deferred or {})):
            raise ValueError("deferred panel names must not be empty")
        return self


def load_nl2al_manifest(dataset_dir: Path) -> NL2ALManifest:
    path = dataset_dir / NL2AL_MANIFEST_FILENAME
    try:
        data = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read NL2AL dataset manifest at {path}: {exc}") from exc

    try:
        return NL2ALManifest.model_validate_json(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid NL2AL dataset manifest at {path}: {exc}") from exc
