import os
import stat
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_lifecycle import (
    BugFixLifecyclePaths,
    TrustedSource,
    TrustedWorkspaceBuilder,
    materialized_workspace_tree_hash,
)
from bcbench.evaluate.bugfix_lifecycle import workspace as workspace_module


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


def _create_post_checkout_hook(directory: Path, marker: Path) -> None:
    directory.mkdir(parents=True)
    hook = directory / "post-checkout"
    hook.write_text(f"#!/bin/sh\nprintf ambient > '{marker.as_posix()}'\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def _lifecycle_paths(tmp_path: Path, *, baseline_workspace: Path | None = None) -> BugFixLifecyclePaths:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    return BugFixLifecyclePaths(
        entry_root=entry_root,
        baseline_workspace=baseline_workspace or entry_root / "baseline",
        agent_workspace=entry_root / "agent",
        agent_logs=entry_root / "agent-logs",
        agent_tools=entry_root / "agent-tools",
        mounted_staging=entry_root / "staging",
        evaluator_workspaces=entry_root / "evaluators",
        evidence=entry_root / "evidence",
        protected_root=protected_root,
        trusted_source=protected_root / "repository.git",
        checkpoints=protected_root / "checkpoints",
        final_results=protected_root / "final-results",
    )


def _object_files(repository: Path) -> dict[str, Path]:
    objects = repository / "objects"
    return {sha256(path.read_bytes()).hexdigest(): path for path in objects.rglob("*") if path.is_file()}


def _create_junction(junction: Path, target: Path) -> None:
    target.mkdir(parents=True)
    junction.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"Directory junction creation is unavailable: {result.stderr or result.stdout}")


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

    builder = TrustedWorkspaceBuilder(paths)
    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    workspace = builder.create_evaluator_workspace(trusted_source, "replace-ref")

    assert trusted_source.commit == replacement_commit
    assert _git("--git-dir", str(trusted_source.repository), "--no-replace-objects", "cat-file", "-t", trusted_source.commit, cwd=tmp_path) == "commit"
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "replacement\n"


def test_git_environment_removes_all_inherited_git_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.hooksPath'='ambient'")
    monkeypatch.setenv("GIT_COMMON_DIR", "ambient-common")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", "ambient-template")
    monkeypatch.setenv("git_object_directory", "ambient-objects")
    monkeypatch.setenv("Git_Replace_Ref_Base", "ambient-replacements")

    environment = workspace_module._git_environment()

    assert {name: value for name, value in environment.items() if name.upper().startswith("GIT_")} == {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def test_capture_and_clone_ignore_ambient_git_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _lifecycle_paths(tmp_path)
    trusted_commit = _create_repository(paths.baseline_workspace)
    ambient_repository = tmp_path / "ambient-repository"
    _create_repository(ambient_repository)
    marker = tmp_path / "ambient-hook-ran"
    configured_hooks = tmp_path / "configured-hooks"
    template = tmp_path / "template"
    _create_post_checkout_hook(configured_hooks, marker)
    _create_post_checkout_hook(template / "hooks", marker)
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.hooksPath'='{configured_hooks.as_posix()}'")
    monkeypatch.setenv("GIT_COMMON_DIR", str(ambient_repository / ".git"))
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))

    builder = TrustedWorkspaceBuilder(paths)
    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    workspace = builder.create_evaluator_workspace(trusted_source, "ambient")

    assert trusted_source.commit == trusted_commit
    assert _git("rev-parse", "HEAD", cwd=workspace) == trusted_commit
    assert not marker.exists()
    assert not (trusted_source.repository / "hooks" / "post-checkout").exists()
    assert not (workspace / ".git" / "hooks" / "post-checkout").exists()


def test_materialized_tree_hash_includes_relevant_files_and_excludes_ephemeral_outputs(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    _create_repository(repository)
    (repository / ".gitignore").write_text("ignored.al\n", encoding="utf-8")
    (repository / "ignored.al").write_text("codeunit 1 Ignored {}\n", encoding="utf-8")
    (repository / "untracked.al").write_text("codeunit 2 Untracked {}\n", encoding="utf-8")
    (repository / "src" / "output").mkdir(parents=True)
    (repository / "src" / "output" / "App.app").write_bytes(b"package")
    (repository / "src" / ".alpackages").mkdir()
    (repository / "src" / ".alpackages" / "Dependency.app").write_bytes(b"dependency")
    (repository / "evidence").mkdir()
    (repository / "evidence" / "stdout.txt").write_text("output", encoding="utf-8")

    initial_hash = materialized_workspace_tree_hash(repository)

    (repository / "src" / "output" / "App.app").write_bytes(b"changed package")
    (repository / "src" / ".alpackages" / "Dependency.app").write_bytes(b"changed dependency")
    (repository / "evidence" / "stdout.txt").write_text("changed output", encoding="utf-8")
    assert materialized_workspace_tree_hash(repository) == initial_hash

    (repository / "ignored.al").write_text("codeunit 1 Ignored { trigger OnRun() begin end; }\n", encoding="utf-8")
    assert materialized_workspace_tree_hash(repository) != initial_hash


def test_materialized_tree_hash_detects_missing_files_and_rejects_non_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    _create_repository(repository)
    expected_hash = materialized_workspace_tree_hash(repository)

    (repository / "tracked.txt").unlink()

    assert materialized_workspace_tree_hash(repository) != expected_hash
    with pytest.raises(ValueError, match="Git repository"):
        materialized_workspace_tree_hash(tmp_path / "missing")


def test_builder_rejects_forged_trusted_commit_that_exists(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    earlier_commit = _create_repository(paths.baseline_workspace)
    (paths.baseline_workspace / "tracked.txt").write_text("latest\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=paths.baseline_workspace)
    _git("commit", "-m", "latest", cwd=paths.baseline_workspace)
    builder = TrustedWorkspaceBuilder(paths)
    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    forged_source = TrustedSource(repository=trusted_source.repository, commit=earlier_commit)

    with pytest.raises(ValueError, match="commit"):
        builder.create_agent_workspace(forged_source)


def test_builder_rejects_forged_trusted_repository_containing_commit(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    _create_repository(paths.baseline_workspace)
    builder = TrustedWorkspaceBuilder(paths)
    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    forged_repository = paths.protected_root / "forged.git"
    _git("clone", "--bare", str(trusted_source.repository), str(forged_repository), cwd=tmp_path)
    forged_source = TrustedSource(repository=forged_repository, commit=trusted_source.commit)

    with pytest.raises(ValueError, match="repository"):
        builder.create_agent_workspace(forged_source)


def test_agent_clone_does_not_hardlink_protected_git_objects(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    _create_repository(paths.baseline_workspace)
    builder = TrustedWorkspaceBuilder(paths)
    trusted_source = builder.capture_trusted_source(paths.baseline_workspace)
    agent_workspace = builder.create_agent_workspace(trusted_source)
    protected_objects = _object_files(paths.trusted_source)
    agent_objects = _object_files(agent_workspace / ".git")
    common_digests = protected_objects.keys() & agent_objects.keys()

    assert common_digests
    for digest in common_digests:
        assert not protected_objects[digest].samefile(agent_objects[digest])

    agent_object = agent_objects[next(iter(common_digests))]
    agent_object.chmod(stat.S_IWRITE)
    agent_object.unlink()
    assert _git("--git-dir", str(paths.trusted_source), "fsck", "--no-dangling", cwd=tmp_path) == ""


def test_builder_rejects_managed_path_escape(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path, baseline_workspace=tmp_path / "outside")

    with pytest.raises(ValueError, match="entry_root"):
        TrustedWorkspaceBuilder(paths)


def test_builder_rejects_trusted_source_outside_protected_root(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    escaped = BugFixLifecyclePaths(**{**paths.__dict__, "trusted_source": paths.entry_root / "repository.git"})

    with pytest.raises(ValueError, match="protected_root"):
        TrustedWorkspaceBuilder(escaped)


def test_builder_rejects_overlapping_baseline_and_protected_root(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    overlapping = BugFixLifecyclePaths(**{**paths.__dict__, "protected_root": paths.baseline_workspace})

    with pytest.raises(ValueError, match="disjoint"):
        TrustedWorkspaceBuilder(overlapping)


def test_builder_rejects_agent_visible_final_results(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    exposed = BugFixLifecyclePaths(**{**paths.__dict__, "final_results": paths.entry_root / "final-results"})

    with pytest.raises(ValueError, match="protected_root"):
        TrustedWorkspaceBuilder(exposed)


def test_builder_rejects_final_results_equal_to_protected_root(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    equal_root = BugFixLifecyclePaths(**{**paths.__dict__, "final_results": paths.protected_root})

    with pytest.raises(ValueError, match="protected_root"):
        TrustedWorkspaceBuilder(equal_root)


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


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
def test_builder_rejects_junction_intermediate(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    junction = paths.entry_root / "redirect"
    _create_junction(junction, tmp_path / "outside")
    redirected = BugFixLifecyclePaths(**{**paths.__dict__, "baseline_workspace": junction / "baseline"})

    with pytest.raises(ValueError, match="reparse point"):
        TrustedWorkspaceBuilder(redirected)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
def test_builder_rejects_junction_ancestor_aliasing_protected_root_beneath_entry_root(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    alias = tmp_path / "entry-alias"
    _create_junction(alias, paths.entry_root)
    protected_root = alias / "protected"
    aliased = BugFixLifecyclePaths(
        **{
            **paths.__dict__,
            "protected_root": protected_root,
            "trusted_source": protected_root / "repository.git",
            "checkpoints": protected_root / "checkpoints",
            "final_results": protected_root / "final-results",
        }
    )

    with pytest.raises(ValueError, match="reparse point"):
        TrustedWorkspaceBuilder(aliased)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
@pytest.mark.parametrize(
    ("field", "root_name", "relative_path"),
    [
        ("baseline_workspace", "entry_root", Path("baseline")),
        ("trusted_source", "protected_root", Path("repository.git")),
    ],
)
def test_builder_rejects_equivalent_target_junction_aliases(tmp_path: Path, field: str, root_name: str, relative_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    root = getattr(paths, root_name)
    alias = tmp_path / f"{root.name}-alias"
    _create_junction(alias, root)
    aliased = BugFixLifecyclePaths(**{**paths.__dict__, field: alias / relative_path})

    with pytest.raises(ValueError, match="reparse point"):
        TrustedWorkspaceBuilder(aliased)
