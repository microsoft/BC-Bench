from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO_ROOT / "dataset"
MANIFEST_NAME = "nl2al_manifest.json"
PANEL_CONTRACT = {
    "gold": ("nl2al.jsonl", "single_turn"),
    "challenge": ("nl2al_challenge.jsonl", "single_turn"),
    "multiturn": ("nl2al_multiturn.jsonl", "final_artifact"),
}
GENERATED_FILES = (*(file for file, _scope in PANEL_CONTRACT.values()), MANIFEST_NAME)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GENERATOR_PATTERN = re.compile(r"^Export-BCalDataset\.ps1/[A-Za-z0-9][A-Za-z0-9._-]*$")


class DatasetImportError(ValueError):
    pass


@dataclass(frozen=True)
class PanelDefinition:
    name: str
    file: str
    count: int
    sha256: str


@dataclass(frozen=True)
class ImportResult:
    destination: Path
    updated_files: tuple[str, ...]


def _expect_object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DatasetImportError(f"{context} must be a JSON object")
    return cast(dict[str, object], value)


def _require_exact_keys(
    value: Mapping[str, object],
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    actual = set(value)
    allowed = required | (optional or set())
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise DatasetImportError(f"{context} has {'; '.join(details)}")


def _expect_string(value: Mapping[str, object], key: str, context: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item.strip():
        raise DatasetImportError(f"{context}.{key} must be a non-empty string")
    return item


def _expect_non_negative_int(value: Mapping[str, object], key: str, context: str) -> int:
    item = value[key]
    if type(item) is not int or item < 0:
        raise DatasetImportError(f"{context}.{key} must be a non-negative integer")
    return item


def _expect_sha256(value: Mapping[str, object], key: str, context: str) -> str:
    item = _expect_string(value, key, context)
    if not SHA256_PATTERN.fullmatch(item):
        raise DatasetImportError(f"{context}.{key} must be a lowercase SHA-256 digest")
    return item


def _validate_deferred(value: object, selected_files: set[str]) -> None:
    deferred = _expect_object(value, "manifest.deferred")
    deferred_files: set[str] = set()
    for name, raw_entry in deferred.items():
        if not name.strip():
            raise DatasetImportError("manifest.deferred panel names must not be empty")
        context = f"manifest.deferred.{name}"
        entry = _expect_object(raw_entry, context)
        _require_exact_keys(entry, {"file", "count", "sha256", "evaluation_scope", "reason"}, context)
        file = _expect_string(entry, "file", context)
        if Path(file).name != file or not file.endswith(".jsonl"):
            raise DatasetImportError(f"{context}.file must be a JSONL file name without directories")
        if file in selected_files or file in deferred_files:
            raise DatasetImportError(f"{context}.file must be unique and must not overlap selectable panels")
        deferred_files.add(file)
        _expect_non_negative_int(entry, "count", context)
        _expect_sha256(entry, "sha256", context)
        if _expect_string(entry, "evaluation_scope", context) != "deferred":
            raise DatasetImportError(f"{context}.evaluation_scope must be 'deferred'")
        _expect_string(entry, "reason", context)


def _validate_manifest(data: bytes) -> tuple[PanelDefinition, ...]:
    try:
        decoded: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetImportError(f"{MANIFEST_NAME} is not valid UTF-8 JSON: {exc}") from exc

    manifest = _expect_object(decoded, "manifest")
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "version",
            "source_canonical_sha256",
            "status",
            "source_repository",
            "source_commit",
            "source_dataset",
            "source_schema_version",
            "imported_from",
            "generator",
            "panels",
        },
        "manifest",
        optional={"deferred"},
    )
    if _expect_string(manifest, "schema_version", "manifest") != "1.0":
        raise DatasetImportError("manifest.schema_version must be '1.0'")
    _expect_string(manifest, "version", "manifest")
    _expect_sha256(manifest, "source_canonical_sha256", "manifest")
    _expect_string(manifest, "status", "manifest")
    if _expect_string(manifest, "source_repository", "manifest") != "bic/BC-DeveloperExperience":
        raise DatasetImportError("manifest.source_repository must be 'bic/BC-DeveloperExperience'")
    if not COMMIT_PATTERN.fullmatch(_expect_string(manifest, "source_commit", "manifest")):
        raise DatasetImportError("manifest.source_commit must be a lowercase 40-character Git commit")
    _expect_string(manifest, "source_dataset", "manifest")
    _expect_string(manifest, "source_schema_version", "manifest")

    imported_from = _expect_object(manifest["imported_from"], "manifest.imported_from")
    _require_exact_keys(imported_from, {"repository", "ref", "commit"}, "manifest.imported_from")
    if _expect_string(imported_from, "repository", "manifest.imported_from") != "microsoft/BC-Bench":
        raise DatasetImportError("manifest.imported_from.repository must be 'microsoft/BC-Bench'")
    _expect_string(imported_from, "ref", "manifest.imported_from")
    if not COMMIT_PATTERN.fullmatch(_expect_string(imported_from, "commit", "manifest.imported_from")):
        raise DatasetImportError("manifest.imported_from.commit must be a lowercase 40-character Git commit")
    if not GENERATOR_PATTERN.fullmatch(_expect_string(manifest, "generator", "manifest")):
        raise DatasetImportError("manifest.generator must identify a versioned Export-BCalDataset.ps1 generator")

    panels = _expect_object(manifest["panels"], "manifest.panels")
    expected_panels = set(PANEL_CONTRACT)
    actual_panels = set(panels)
    missing_panels = sorted(expected_panels - actual_panels)
    unknown_panels = sorted(actual_panels - expected_panels)
    if missing_panels or unknown_panels:
        details = []
        if missing_panels:
            details.append(f"missing panels: {', '.join(missing_panels)}")
        if unknown_panels:
            details.append(f"unknown panels: {', '.join(unknown_panels)}")
        raise DatasetImportError(f"manifest.panels has {'; '.join(details)}")

    definitions = []
    for name, (expected_file, expected_scope) in PANEL_CONTRACT.items():
        context = f"manifest.panels.{name}"
        panel = _expect_object(panels[name], context)
        _require_exact_keys(panel, {"file", "count", "sha256", "evaluation_scope"}, context)
        file = _expect_string(panel, "file", context)
        if file != expected_file:
            raise DatasetImportError(f"{context}.file must be {expected_file!r}")
        if _expect_string(panel, "evaluation_scope", context) != expected_scope:
            raise DatasetImportError(f"{context}.evaluation_scope must be {expected_scope!r}")
        definitions.append(
            PanelDefinition(
                name=name,
                file=file,
                count=_expect_non_negative_int(panel, "count", context),
                sha256=_expect_sha256(panel, "sha256", context),
            )
        )

    if "deferred" in manifest:
        _validate_deferred(manifest["deferred"], {definition.file for definition in definitions})
    return tuple(definitions)


def _read_instance_ids(data: bytes, panel: PanelDefinition) -> tuple[str, ...]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DatasetImportError(f"{panel.file} is not valid UTF-8: {exc}") from exc

    instance_ids = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise DatasetImportError(f"{panel.file}:{line_number} is blank")
        try:
            decoded: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetImportError(f"{panel.file}:{line_number} is not valid JSON: {exc}") from exc
        row = _expect_object(decoded, f"{panel.file}:{line_number}")
        instance_id = row.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise DatasetImportError(f"{panel.file}:{line_number} is missing a non-empty string instance_id")
        instance_ids.append(instance_id)
    return tuple(instance_ids)


def validate_generated_bundle(source: Path) -> dict[str, bytes]:
    if not source.is_dir():
        raise DatasetImportError(f"Generated dataset source directory does not exist: {source}")

    actual_files = {path.name for path in source.iterdir()}
    expected_files = set(GENERATED_FILES)
    missing_files = sorted(expected_files - actual_files)
    unknown_files = sorted(actual_files - expected_files)
    if missing_files or unknown_files:
        details = []
        if missing_files:
            details.append(f"missing files: {', '.join(missing_files)}")
        if unknown_files:
            details.append(f"unknown files: {', '.join(unknown_files)}")
        raise DatasetImportError(f"Generated dataset folder has {'; '.join(details)}")
    for name in GENERATED_FILES:
        if not (source / name).is_file():
            raise DatasetImportError(f"Generated dataset path is not a file: {source / name}")

    payload = {name: (source / name).read_bytes() for name in GENERATED_FILES}
    panels = _validate_manifest(payload[MANIFEST_NAME])
    seen_ids: dict[str, str] = {}
    for panel in panels:
        data = payload[panel.file]
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != panel.sha256:
            raise DatasetImportError(f"SHA-256 mismatch for panel {panel.name!r} file {panel.file!r}: expected {panel.sha256}, got {actual_hash}")
        instance_ids = _read_instance_ids(data, panel)
        if len(instance_ids) != panel.count:
            raise DatasetImportError(f"Row count mismatch for panel {panel.name!r}: expected {panel.count}, got {len(instance_ids)}")
        for instance_id in instance_ids:
            if previous_panel := seen_ids.get(instance_id):
                raise DatasetImportError(f"Duplicate instance_id {instance_id!r} in panels {previous_panel!r} and {panel.name!r}")
            seen_ids[instance_id] = panel.name
    return payload


def sync_bcal_dataset(source: Path, destination: Path = DATASET_DIR) -> ImportResult:
    payload = validate_generated_bundle(source)
    destination.mkdir(parents=True, exist_ok=True)
    updated_files = tuple(name for name in GENERATED_FILES if not (destination / name).is_file() or (destination / name).read_bytes() != payload[name])
    if not updated_files:
        return ImportResult(destination=destination, updated_files=())

    staged: dict[str, Path] = {}
    try:
        for name in updated_files:
            file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=destination)
            with os.fdopen(file_descriptor, "wb") as temp_file:
                temp_file.write(payload[name])
                temp_file.flush()
                os.fsync(temp_file.fileno())
            staged[name] = Path(temp_name)
        for name in updated_files:
            staged.pop(name).replace(destination / name)
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)

    return ImportResult(destination=destination, updated_files=updated_files)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and sync a generated BCal dataset bundle into BC-Bench.")
    parser.add_argument("--source", required=True, type=Path, help="Folder produced by Export-BCalDataset.ps1")
    args = parser.parse_args(argv)
    try:
        result = sync_bcal_dataset(args.source)
    except DatasetImportError as exc:
        parser.error(str(exc))

    if result.updated_files:
        print(f"Updated {result.destination}: {', '.join(result.updated_files)}")
    else:
        print(f"BCal dataset is already up to date: {result.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
