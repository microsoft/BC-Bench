from pathlib import Path
from shutil import copytree
from unittest.mock import MagicMock

import pytest
import yaml

from bcbench.operations.instruction_operations import setup_agent_playbooks
from bcbench.playbooks import (
    PlaybookManifest,
    PlaybookSetup,
    load_playbook_manifest,
    playbook_revision,
    resolve_playbook_for_area,
    resolve_playbook_for_paths,
)
from bcbench.types import AgentHarness

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


def install_package(tmp_path: Path, harness: AgentHarness) -> Path:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = write_package(source_root)
    target = harness.get_target_dir(tmp_path) / "agents" / "fix-bug" / "playbooks"
    copytree(source, target)
    return target


def entry_with_area(area: str | None) -> MagicMock:
    entry = MagicMock()
    entry.metadata.area = area
    return entry


@pytest.mark.parametrize(
    ("harness", "target_dir"),
    [
        (AgentHarness.COPILOT, ".github"),
        (AgentHarness.CLAUDE, ".claude"),
    ],
)
def test_selected_mode_writes_harness_specific_marker(tmp_path: Path, harness: AgentHarness, target_dir: str):
    install_package(tmp_path, harness)

    setup = setup_agent_playbooks(
        {"playbooks": {"enabled": True, "mode": "selected"}},
        entry_with_area("warehouse"),
        tmp_path,
        harness=harness,
        custom_agent="fix-bug",
    )

    marker = tmp_path / target_dir / "agents" / "fix-bug" / "playbooks" / "selected.yaml"
    assert setup == PlaybookSetup(
        enabled=True,
        mode="selected",
        revision=setup.revision,
        playbook_id="warehouse",
    )
    assert setup.revision
    assert yaml.safe_load(marker.read_text(encoding="utf-8")) == {"id": "warehouse", "file": "warehouse.md"}


def test_discover_mode_validates_package_without_marker(tmp_path: Path):
    playbook_dir = install_package(tmp_path, AgentHarness.COPILOT)

    setup = setup_agent_playbooks(
        {"playbooks": {"enabled": True, "mode": "discover"}},
        entry_with_area("warehouse"),
        tmp_path,
        harness=AgentHarness.COPILOT,
        custom_agent="fix-bug",
    )

    assert setup.enabled is True
    assert setup.mode == "discover"
    assert setup.playbook_id is None
    assert not (playbook_dir / "selected.yaml").exists()


def test_disabled_playbooks_do_not_require_custom_agent(tmp_path: Path):
    setup = setup_agent_playbooks(
        {"playbooks": {"enabled": False, "mode": "discover"}},
        entry_with_area("warehouse"),
        tmp_path,
        harness=AgentHarness.COPILOT,
        custom_agent=None,
    )

    assert setup == PlaybookSetup()


def test_selected_mode_with_unmapped_area_removes_stale_marker(tmp_path: Path):
    playbook_dir = install_package(tmp_path, AgentHarness.COPILOT)
    marker = playbook_dir / "selected.yaml"
    marker.write_text("id: stale\nfile: stale.md\n", encoding="utf-8")

    setup = setup_agent_playbooks(
        {"playbooks": {"enabled": True, "mode": "selected"}},
        entry_with_area("sales"),
        tmp_path,
        harness=AgentHarness.COPILOT,
        custom_agent="fix-bug",
    )

    assert setup.playbook_id is None
    assert not marker.exists()


def test_enabled_playbooks_require_custom_agent(tmp_path: Path):
    with pytest.raises(ValueError, match="playbooks require a custom agent"):
        setup_agent_playbooks(
            {"playbooks": {"enabled": True, "mode": "discover"}},
            entry_with_area("warehouse"),
            tmp_path,
            harness=AgentHarness.COPILOT,
            custom_agent=None,
        )


def test_invalid_playbook_mode_fails(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid playbook mode"):
        setup_agent_playbooks(
            {"playbooks": {"enabled": True, "mode": "automatic"}},
            entry_with_area("warehouse"),
            tmp_path,
            harness=AgentHarness.COPILOT,
            custom_agent="fix-bug",
        )


@pytest.mark.parametrize("profile", ["microsoft-BCApps", "microsoftInternal-NAV"])
def test_fix_bug_agent_forbids_delegation_and_background_work(profile: str):
    agent_file = Path("src/bcbench/agent/shared/instructions") / profile / "agents" / "fix-bug.agent.md"
    content = agent_file.read_text(encoding="utf-8")

    assert "Do not use the Agent tool" in content
    assert "Do not delegate" in content
    assert "Do not start background work" in content
    assert "Execute the workflow directly in this agent" in content
