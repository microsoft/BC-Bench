from pathlib import Path

import pytest

from bcbench.agent.shared.playbooks import (
    PlaybookManifest,
    load_playbook_manifest,
    playbook_revision,
    resolve_playbook_for_area,
    resolve_playbook_for_paths,
)


MANIFEST = """\
playbooks:
  - id: warehouse
    file: warehouse.md
    areas: [warehouse]
    paths:
      - App/Layers/W1/BaseApp/Warehouse/**
  - id: project
    file: project.md
    areas: [project]
    paths:
      - App/Layers/W1/BaseApp/Projects/**
"""


def write_package(tmp_path: Path, manifest: str = MANIFEST) -> Path:
    playbook_dir = tmp_path / "playbooks"
    playbook_dir.mkdir()
    (playbook_dir / "manifest.yaml").write_text(manifest, encoding="utf-8")
    (playbook_dir / "warehouse.md").write_text("# Warehouse\n", encoding="utf-8")
    (playbook_dir / "project.md").write_text("# Project\n", encoding="utf-8")
    return playbook_dir


def test_loads_valid_manifest(tmp_path: Path):
    manifest = load_playbook_manifest(write_package(tmp_path))

    assert isinstance(manifest, PlaybookManifest)
    assert [playbook.id for playbook in manifest.playbooks] == ["warehouse", "project"]


@pytest.mark.parametrize(
    ("area", "expected"),
    [
        ("warehouse", "warehouse"),
        ("WAREHOUSE", "warehouse"),
        ("project", "project"),
        ("sales", None),
        (None, None),
    ],
)
def test_resolves_area_case_insensitively(tmp_path: Path, area: str | None, expected: str | None):
    manifest = load_playbook_manifest(write_package(tmp_path))

    selected = resolve_playbook_for_area(manifest, area)

    assert (selected.id if selected else None) == expected


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["App/Layers/W1/BaseApp/Warehouse/Activity/Foo.Codeunit.al"], "warehouse"),
        (["app/layers/w1/baseapp/projects/project/posting/foo.codeunit.al"], "project"),
        (["App/Layers/W1/BaseApp/Sales/Foo.Codeunit.al"], None),
        (
            [
                "App/Layers/W1/BaseApp/Warehouse/Activity/Foo.Codeunit.al",
                "App/Layers/W1/BaseApp/Projects/Project/Foo.Codeunit.al",
            ],
            None,
        ),
    ],
)
def test_resolves_paths_only_for_one_distinct_playbook(tmp_path: Path, paths: list[str], expected: str | None):
    manifest = load_playbook_manifest(write_package(tmp_path))

    selected = resolve_playbook_for_paths(manifest, paths)

    assert (selected.id if selected else None) == expected


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        (MANIFEST.replace("id: project", "id: warehouse"), "duplicate playbook id"),
        (MANIFEST.replace("areas: [project]", "areas: [warehouse]"), "duplicate area alias"),
        (MANIFEST.replace("project.md", "missing.md"), "missing playbook file"),
        (MANIFEST.replace("App/Layers/W1/BaseApp/Projects/**", "App/Layers/W1/BaseApp/Warehouse/Activity/**"), "overlapping playbook paths"),
    ],
)
def test_rejects_invalid_package(tmp_path: Path, manifest: str, message: str):
    with pytest.raises(ValueError, match=message):
        load_playbook_manifest(write_package(tmp_path, manifest))


def test_rejects_path_without_recursive_suffix(tmp_path: Path):
    manifest = MANIFEST.replace("App/Layers/W1/BaseApp/Projects/**", "App/Layers/W1/BaseApp/Projects/*")

    with pytest.raises(ValueError, match="must end with '/\\*\\*'"):
        load_playbook_manifest(write_package(tmp_path, manifest))


def test_revision_changes_with_playbook_content(tmp_path: Path):
    playbook_dir = write_package(tmp_path)
    manifest = load_playbook_manifest(playbook_dir)
    original = playbook_revision(playbook_dir, manifest)

    (playbook_dir / "warehouse.md").write_text("# Warehouse changed\n", encoding="utf-8")

    assert playbook_revision(playbook_dir, manifest) != original
