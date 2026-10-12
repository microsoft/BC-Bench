import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from tools.import_bcal_dataset import GENERATED_FILES, DatasetImportError, sync_bcal_dataset


def write_manifest(source: Path, manifest: dict[str, Any]) -> None:
    (source / "nl2al_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def create_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    source = tmp_path / "generated"
    source.mkdir()
    rows = {
        "gold": [{"instance_id": "gold-1"}],
        "challenge": [{"instance_id": "challenge-1"}],
        "multiturn": [{"instance_id": "multiturn-1"}],
    }
    files = {
        "gold": "nl2al.jsonl",
        "challenge": "nl2al_challenge.jsonl",
        "multiturn": "nl2al_multiturn.jsonl",
    }
    scopes = {
        "gold": "single_turn",
        "challenge": "single_turn",
        "multiturn": "final_artifact",
    }
    panels = {}
    for name, file in files.items():
        data = "".join(json.dumps(row) + "\n" for row in rows[name]).encode()
        (source / file).write_bytes(data)
        panels[name] = {
            "file": file,
            "count": len(rows[name]),
            "sha256": sha256(data).hexdigest(),
            "evaluation_scope": scopes[name],
        }
    manifest = {
        "schema_version": "1.0",
        "version": "test-version",
        "source_canonical_sha256": "a" * 64,
        "status": "candidate",
        "source_repository": "bic/BC-DeveloperExperience",
        "source_commit": "b" * 40,
        "source_dataset": "test-source",
        "source_schema_version": "1.0",
        "imported_from": {
            "repository": "microsoft/BC-Bench",
            "ref": "bcal/dataset-panels",
            "commit": "c" * 40,
        },
        "generator": "Export-BCalDataset.ps1/1.0",
        "panels": panels,
        "deferred": {
            "quarantine": {
                "file": "nl2al_quarantine.jsonl",
                "count": 2,
                "sha256": "d" * 64,
                "evaluation_scope": "deferred",
                "reason": "Not selectable.",
            }
        },
    }
    write_manifest(source, manifest)
    return source, manifest


def refresh_panel_hash(source: Path, manifest: dict[str, Any], panel: str) -> None:
    panel_manifest = manifest["panels"][panel]
    panel_manifest["sha256"] = sha256((source / panel_manifest["file"]).read_bytes()).hexdigest()
    write_manifest(source, manifest)


def test_valid_import_is_repeatable_and_updates_only_generated_files(tmp_path):
    source, _manifest = create_bundle(tmp_path)
    destination = tmp_path / "dataset"
    destination.mkdir()
    unrelated = destination / "other.jsonl"
    unrelated.write_text("leave me alone\n", encoding="utf-8")

    first = sync_bcal_dataset(source, destination)
    mtimes = {name: (destination / name).stat().st_mtime_ns for name in GENERATED_FILES}
    second = sync_bcal_dataset(source, destination)

    assert first.updated_files == GENERATED_FILES
    assert second.updated_files == ()
    assert {name: (destination / name).stat().st_mtime_ns for name in GENERATED_FILES} == mtimes
    assert unrelated.read_text(encoding="utf-8") == "leave me alone\n"
    assert all((destination / name).read_bytes() == (source / name).read_bytes() for name in GENERATED_FILES)


def test_import_rejects_hash_mismatch(tmp_path):
    source, _manifest = create_bundle(tmp_path)
    (source / "nl2al.jsonl").write_text('{"instance_id": "changed"}\n', encoding="utf-8")

    with pytest.raises(DatasetImportError, match="SHA-256 mismatch"):
        sync_bcal_dataset(source, tmp_path / "dataset")


def test_import_rejects_count_mismatch(tmp_path):
    source, manifest = create_bundle(tmp_path)
    manifest["panels"]["gold"]["count"] = 2
    write_manifest(source, manifest)

    with pytest.raises(DatasetImportError, match="Row count mismatch"):
        sync_bcal_dataset(source, tmp_path / "dataset")


def test_import_rejects_duplicate_ids_across_panels(tmp_path):
    source, manifest = create_bundle(tmp_path)
    (source / "nl2al_challenge.jsonl").write_text('{"instance_id": "gold-1"}\n', encoding="utf-8")
    refresh_panel_hash(source, manifest, "challenge")

    with pytest.raises(DatasetImportError, match="Duplicate instance_id"):
        sync_bcal_dataset(source, tmp_path / "dataset")


def test_import_rejects_missing_instance_id(tmp_path):
    source, manifest = create_bundle(tmp_path)
    (source / "nl2al.jsonl").write_text('{"prompt": "missing id"}\n', encoding="utf-8")
    refresh_panel_hash(source, manifest, "gold")

    with pytest.raises(DatasetImportError, match="missing a non-empty string instance_id"):
        sync_bcal_dataset(source, tmp_path / "dataset")


@pytest.mark.parametrize(("panel_change", "message"), [("missing", "missing panels"), ("unknown", "unknown panels")])
def test_import_rejects_missing_or_unknown_panels(tmp_path, panel_change, message):
    source, manifest = create_bundle(tmp_path)
    if panel_change == "missing":
        del manifest["panels"]["multiturn"]
    else:
        manifest["panels"]["experimental"] = manifest["panels"]["gold"]
    write_manifest(source, manifest)

    with pytest.raises(DatasetImportError, match=message):
        sync_bcal_dataset(source, tmp_path / "dataset")


@pytest.mark.parametrize(("file_change", "message"), [("missing", "missing files"), ("unknown", "unknown files")])
def test_import_rejects_missing_or_unknown_files(tmp_path, file_change, message):
    source, _manifest = create_bundle(tmp_path)
    if file_change == "missing":
        (source / "nl2al_multiturn.jsonl").unlink()
    else:
        (source / "notes.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(DatasetImportError, match=message):
        sync_bcal_dataset(source, tmp_path / "dataset")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_repository", "example/private", "source_repository"),
        ("source_commit", "not-a-commit", "source_commit"),
        ("generator", "unknown-generator", "generator"),
    ],
)
def test_import_rejects_invalid_provenance(tmp_path, field, value, message):
    source, manifest = create_bundle(tmp_path)
    manifest[field] = value
    write_manifest(source, manifest)

    with pytest.raises(DatasetImportError, match=message):
        sync_bcal_dataset(source, tmp_path / "dataset")
