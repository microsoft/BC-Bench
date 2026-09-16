import os
import subprocess
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_lifecycle import BugFixLifecyclePaths, TrustedWorkspaceBuilder


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _create_repository(path: Path) -> str:
    path.mkdir(parents=True)
    _git("init", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test User", cwd=path)
    (path / "tracked.txt").write_text("trusted\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=path)
    _git("commit", "-m", "trusted", cwd=path)
    return _git("--no-replace-objects", "rev-parse", "HEAD", cwd=path)


def _lifecycle_paths(tmp_path: Path, *, baseline_workspace: Path | None = None) -> BugFixLifecyclePaths:
    entry_root = tmp_path / "entry"
    protected_root = entry_root / "protected"
    return BugFixLifecyclePaths(
        entry_root=entry_root,
        baseline_workspace=baseline_workspace or entry_root / "baseline",
        agent_workspace=entry_root / "agent",
        agent_logs=entry_root / "agent-logs",
        mounted_staging=entry_root / "staging",
        evaluator_workspaces=entry_root / "evaluators",
        evidence=entry_root / "evidence",
        protected_root=protected_root,
        trusted_source=protected_root / "repository.git",
        checkpoints=entry_root / "checkpoints",
        final_results=entry_root / "final-results",
    )


def test_trusted_workspaces_are_independent_and_ignore_agent_git_state(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    trusted_commit = _create_repository(paths.baseline_workspace)
    builder = TrustedWorkspaceBuilder(paths)

    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    builder.remove_baseline_workspace()
    agent_workspace = builder.create_agent_workspace(trusted_source)
    first_evaluator = builder.create_evaluator_workspace(trusted_source, "test-red")

    assert trusted_source.commit == trusted_commit
    assert trusted_source.repository == paths.trusted_source.resolve()
    assert not paths.baseline_workspace.exists()
    assert _git("rev-parse", "HEAD", cwd=agent_workspace) == trusted_commit
    assert _git("rev-parse", "HEAD", cwd=first_evaluator) == trusted_commit
    assert agent_workspace != first_evaluator

    (agent_workspace / "tracked.txt").write_text("agent change\n", encoding="utf-8")
    _git("config", "user.email", "agent@example.com", cwd=agent_workspace)
    _git("config", "user.name", "Agent", cwd=agent_workspace)
    _git("add", "tracked.txt", cwd=agent_workspace)
    _git("commit", "-m", "agent commit", cwd=agent_workspace)
    agent_commit = _git("rev-parse", "HEAD", cwd=agent_workspace)
    _git("replace", trusted_commit, agent_commit, cwd=agent_workspace)
    _git("config", "core.hooksPath", str(agent_workspace / "hooks"), cwd=agent_workspace)

    second_evaluator = builder.create_evaluator_workspace(trusted_source, "test-red")

    assert second_evaluator != first_evaluator
    assert first_evaluator.name.startswith("test-red-")
    assert second_evaluator.name.startswith("test-red-")
    assert _git("rev-parse", "HEAD", cwd=second_evaluator) == trusted_commit
    assert _git("--no-replace-objects", "rev-parse", "HEAD", cwd=second_evaluator) == trusted_commit
    assert (second_evaluator / "tracked.txt").read_text(encoding="utf-8") == "trusted\n"
    assert agent_commit != trusted_commit
    assert _git("--git-dir", str(paths.trusted_source), "--no-replace-objects", "rev-parse", trusted_commit, cwd=tmp_path) == trusted_commit


def test_capture_ignores_baseline_replace_refs(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    trusted_commit = _create_repository(paths.baseline_workspace)
    (paths.baseline_workspace / "tracked.txt").write_text("replacement\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=paths.baseline_workspace)
    _git("commit", "-m", "replacement", cwd=paths.baseline_workspace)
    replacement_commit = _git("rev-parse", "HEAD", cwd=paths.baseline_workspace)
    _git("replace", replacement_commit, trusted_commit, cwd=paths.baseline_workspace)

    trusted_source = TrustedWorkspaceBuilder(paths).capture_trusted_source(paths.baseline_workspace)

    assert trusted_source.commit == replacement_commit
    assert _git("--git-dir", str(trusted_source.repository), "--no-replace-objects", "cat-file", "-t", trusted_source.commit, cwd=tmp_path) == "commit"


def test_builder_rejects_managed_path_escape(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path, baseline_workspace=tmp_path / "outside")

    with pytest.raises(ValueError, match="entry_root"):
        TrustedWorkspaceBuilder(paths)


def test_builder_rejects_trusted_source_outside_protected_root(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    escaped = BugFixLifecyclePaths(**{**paths.__dict__, "trusted_source": paths.entry_root / "repository.git"})

    with pytest.raises(ValueError, match="protected_root"):
        TrustedWorkspaceBuilder(escaped)


def test_remove_baseline_rejects_entry_root_deletion(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path, baseline_workspace=tmp_path / "entry")

    with pytest.raises(ValueError, match="entry_root"):
        TrustedWorkspaceBuilder(paths)


def test_remove_baseline_rejects_symlinked_workspace(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Creating symlinks requires privileges on some Windows configurations")
    paths = _lifecycle_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.entry_root.mkdir()
    paths.baseline_workspace.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        TrustedWorkspaceBuilder(paths)
    assert outside.exists()
