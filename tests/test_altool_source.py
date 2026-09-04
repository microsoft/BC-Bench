import subprocess
from pathlib import Path

from bcbench.agent.shared.altool_source import prepare_altool_source_compatibility


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo(repo: Path) -> str:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def test_temporarily_hides_scope_without_contaminating_agent_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "App"
    project.mkdir(parents=True)
    table = project / "Example.Table.al"
    original = b"\xef\xbb\xbftable 50100 Example\r\n{\r\n    Scope = OnPrem;\r\n}\r\n"
    table.write_bytes(original)
    base_head = _init_repo(repo)

    state = prepare_altool_source_compatibility(repo, ["App"], enabled=True)

    assert _git(repo, "rev-parse", "HEAD") != base_head
    assert _git(repo, "status", "--short") == ""
    assert b"Scope = OnPrem;" not in table.read_bytes()

    table.write_bytes(table.read_bytes() + b"// agent change\r\n")
    state.restore()

    assert _git(repo, "rev-parse", "HEAD") == base_head
    assert table.read_bytes() == original + b"// agent change\r\n"
    diff = _git(repo, "diff")
    assert "agent change" in diff
    assert "BC-Bench AL tool compatibility" not in diff
    assert "-    Scope = OnPrem;" not in diff


def test_only_rewrites_loaded_project_tables(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    loaded = repo / "Loaded" / "Loaded.Table.al"
    outside = repo / "Outside" / "Outside.Table.al"
    loaded.parent.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    loaded.write_text("table 50100 Loaded\n{\n    Scope = OnPrem;\n}\n", encoding="utf-8")
    outside.write_text("table 50101 Outside\n{\n    Scope = OnPrem;\n}\n", encoding="utf-8")
    base_head = _init_repo(repo)

    state = prepare_altool_source_compatibility(repo, ["Loaded"], enabled=True)

    assert "Scope = OnPrem;" not in loaded.read_text(encoding="utf-8")
    assert "Scope = OnPrem;" in outside.read_text(encoding="utf-8")
    state.restore()
    assert _git(repo, "rev-parse", "HEAD") == base_head


def test_agent_can_replace_hidden_scope_property(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "App"
    project.mkdir(parents=True)
    table = project / "Example.Table.al"
    table.write_text("table 50100 Example\n{\n    Scope = OnPrem;\n}\n", encoding="utf-8")
    base_head = _init_repo(repo)

    state = prepare_altool_source_compatibility(repo, ["App"], enabled=True)
    content = table.read_text(encoding="utf-8")
    table.write_text(content.replace("    // BC-Bench AL tool compatibility: hidden Scope = OnPrem 0\n", "    Scope = Cloud;\n"), encoding="utf-8")

    state.restore()

    assert _git(repo, "rev-parse", "HEAD") == base_head
    assert "Scope = Cloud;" in table.read_text(encoding="utf-8")
    assert "BC-Bench AL tool compatibility" not in _git(repo, "diff")


def test_agent_commit_is_preserved_as_worktree_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "App"
    project.mkdir(parents=True)
    table = project / "Example.Table.al"
    table.write_text("table 50100 Example\n{\n    Scope = OnPrem;\n}\n", encoding="utf-8")
    other = project / "Other.Codeunit.al"
    other.write_text("codeunit 50101 Other\n{\n}\n", encoding="utf-8")
    base_head = _init_repo(repo)

    state = prepare_altool_source_compatibility(repo, ["App"], enabled=True)
    other.write_text("codeunit 50101 Other\n{\n    // agent change\n}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "agent change")

    state.restore()

    assert _git(repo, "rev-parse", "HEAD") == base_head
    assert "agent change" in _git(repo, "diff")
    assert "Scope = OnPrem;" in table.read_text(encoding="utf-8")


def test_disabled_compatibility_does_not_require_git_repo(tmp_path: Path) -> None:
    state = prepare_altool_source_compatibility(tmp_path, ["App"], enabled=False)

    state.restore()
