import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bcbench import history_report as history
from bcbench.history_report import build_report, main


def git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def commit_files(repo, message, files, date=None):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", message, date=date)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "History Test")
    git(path, "config", "user.email", "history@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    return path


@pytest.fixture
def remote(repo, monkeypatch):
    monkeypatch.setitem(history.REPOSITORIES, "NAV", repo.as_uri())
    monkeypatch.setattr(history, "_remote_environment", lambda _: {"GIT_NO_LAZY_FETCH": "0"})
    return repo


def test_excludes_cutoff_descendants_and_unrelated_old_branch_but_includes_full_diff(repo):
    root = commit_files(repo, "Initial", {"App/Target.al": "old\n", "App/Mirror.al": "old\n"}, "2025-01-01T00:00:00Z")
    ancestor = commit_files(repo, "Change target and mirror", {"App/Target.al": "historical target\n", "App/Mirror.al": "historical mirror\n"}, "2025-04-01T00:00:00Z")
    cutoff = commit_files(repo, "CUTOFF SECRET", {"App/Target.al": "cutoff secret\n"}, "2025-03-01T00:00:00Z")
    future = commit_files(repo, "FUTURE SECRET", {"App/Target.al": "future secret\n"}, "2025-02-01T00:00:00Z")
    git(repo, "checkout", "-b", "unrelated", root)
    unrelated = commit_files(repo, "UNRELATED SECRET", {"App/Target.al": "unrelated secret\n"}, "2024-01-01T00:00:00Z")

    report = build_report(repo, "NAV", cutoff, [r"App\Target.al"], max_commits=1)

    assert f"## Commit {ancestor}" in report
    assert "historical mirror" in report
    assert "App/Mirror.al" in report
    assert "CUTOFF SECRET" not in report
    assert "cutoff secret" not in report
    assert future not in report
    assert unrelated not in report
    assert "more matching ancestors" in report
    assert git(repo, "rev-parse", "HEAD") == unrelated


def test_multiple_files_select_union_and_deduplicate_commits(repo):
    root = commit_files(repo, "Initial", {"A.al": "a\n", "B.al": "b\n"})
    both = commit_files(repo, "Both", {"A.al": "aa\n", "B.al": "bb\n"})
    only_b = commit_files(repo, "Only B", {"B.al": "bbb\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "x\n"})

    report = build_report(repo, "BCApps", cutoff, ["A.al", "B.al", "A.al"])

    assert report.count(f"## Commit {both}") == 1
    assert f"## Commit {only_b}" in report
    assert f"## Commit {root}" in report
    assert report.index(f"## Commit {only_b}") < report.index(f"## Commit {both}")


def test_commit_selection_pages_without_skipping_or_duplicating_results(repo):
    commits = [commit_files(repo, f"Change {index}", {"A.al": f"{index}\n"}) for index in range(23)]
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["A.al"], max_commits=21)

    assert report.count("## Commit ") == 21
    assert f"## Commit {commits[2]}" in report
    assert f"## Commit {commits[1]}" not in report
    assert "more matching ancestors" in report


def test_root_cutoff_never_falls_back_to_head(repo):
    root = commit_files(repo, "Root", {"A.al": "root\n"})
    commit_files(repo, "Future", {"A.al": "future\n"})

    report = build_report(repo, "NAV", root, ["A.al"])

    assert "No eligible earlier commits" in report
    assert "## Commit" not in report


def test_file_introduced_at_cutoff_has_no_earlier_changes(repo):
    commit_files(repo, "Root", {"Other.al": "root\n"})
    cutoff = commit_files(repo, "Introduce A", {"A.al": "new\n"})

    report = build_report(repo, "NAV", cutoff, ["A.al"])

    assert "No eligible earlier commits" in report


def test_deleted_historical_file_can_be_selected(repo):
    root = commit_files(repo, "Root", {"A.al": "root\n"})
    git(repo, "rm", "A.al")
    git(repo, "commit", "-m", "Delete A")
    deleted = git(repo, "rev-parse", "HEAD")
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["A.al"])

    assert f"## Commit {root}" in report
    assert f"## Commit {deleted}" in report


def test_literal_path_and_markdown_fences(repo):
    commit_files(repo, "Root", {"A[1].al": "old\n", "A1.al": "unrelated\n"})
    ancestor = commit_files(repo, "Change with ``` fence", {"A[1].al": "````\n"})
    other = commit_files(repo, "Other file", {"A1.al": "changed\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["A[1].al"])

    assert f"## Commit {ancestor}" in report
    assert f"## Commit {other}" not in report
    assert "`````diff" in report


def test_merge_ancestors_and_full_first_parent_diff(repo):
    commit_files(repo, "Root", {"A.al": "root\n", "Adjacent.al": "old adjacent\n"})
    git(repo, "checkout", "-b", "feature")
    feature = commit_files(repo, "Feature", {"A.al": "feature\n", "Adjacent.al": "adjacent\n"})
    git(repo, "checkout", "main")
    commit_files(repo, "Main", {"Other.al": "main\n"})
    git(repo, "merge", "--no-ff", "feature", "-m", "Merge feature")
    merge = git(repo, "rev-parse", "HEAD")
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["A.al"])

    assert f"## Commit {merge}" in report
    assert f"## Commit {feature}" in report
    merge_section = report.split(f"## Commit {merge}", 1)[1].split("## Commit", 1)[0]
    assert "Adjacent.al" in merge_section
    assert "+adjacent" in merge_section


def test_merge_cutoff_includes_both_parent_histories(repo):
    commit_files(repo, "Root", {"A.al": "root\n", "B.al": "root\n"})
    git(repo, "checkout", "-b", "feature")
    feature = commit_files(repo, "Feature", {"A.al": "feature\n"})
    git(repo, "checkout", "main")
    main_commit = commit_files(repo, "Main", {"B.al": "main\n"})
    git(repo, "merge", "--no-ff", "feature", "-m", "Cutoff merge")
    cutoff = git(repo, "rev-parse", "HEAD")

    report = build_report(repo, "BCApps", cutoff, ["A.al", "B.al"])

    assert f"## Commit {feature}" in report
    assert f"## Commit {main_commit}" in report
    assert f"## Commit {cutoff}" not in report
    assert "Cutoff merge" not in report


def test_sync_merge_without_selected_file_changes_does_not_consume_limit(repo):
    commit_files(repo, "Root", {"Other.al": "root\n"})
    git(repo, "branch", "upstream")
    selected = commit_files(repo, "Add agent-side file", {"A.al": "selected\n"})
    git(repo, "checkout", "upstream")
    commit_files(repo, "Unrelated upstream change", {"B.al": "unrelated\n"})
    git(repo, "checkout", "main")
    git(repo, "merge", "--no-ff", "upstream", "-m", "Unrelated sync")
    sync = git(repo, "rev-parse", "HEAD")
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "BCApps", cutoff, ["A.al"], max_commits=1)

    assert f"## Commit {selected}" in report
    assert f"## Commit {sync}" not in report
    assert "Unrelated upstream change" not in report
    assert "more matching ancestors" not in report


def test_shallow_history_warns_and_does_not_invent_boundary_diff(repo, tmp_path):
    commit_files(repo, "Root", {"A.al": "root\n"})
    boundary = commit_files(repo, "Boundary", {"A.al": "boundary\n", "NeverChanged.al": "not a new change\n"})
    retained = commit_files(repo, "Retained", {"A.al": "retained\n"})
    cutoff = commit_files(repo, "Cutoff", {"A.al": "cutoff\n"})
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "--depth", "3", repo.as_uri(), str(clone))
    git(clone, "remote", "remove", "origin")

    report = build_report(clone, "NAV", cutoff, ["A.al"])

    assert "**Limited history:**" in report
    assert f"## Commit {retained}" in report
    assert f"## Commit {boundary}" not in report
    assert "NeverChanged.al" not in report
    boundary_report = build_report(clone, "NAV", boundary, ["A.al"])
    assert "**Limited history:**" in boundary_report
    assert "## Commit" not in boundary_report


def test_git_replace_cannot_change_eligible_ancestry(repo):
    root = commit_files(repo, "Root", {"A.al": "root\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})
    future = commit_files(repo, "Future secret", {"A.al": "future\n"})
    git(repo, "replace", cutoff, future)

    report = build_report(repo, "NAV", cutoff, ["A.al"])

    assert f"## Commit {root}" in report
    assert "Future secret" not in report
    assert f"## Commit {future}" not in report


@pytest.mark.parametrize("file", ["", ".", "..", "../A.al", r"C:\A.al", r"\A.al", r"\\server\share\A.al", "C:A.al", "A.al\nB.al"])
def test_rejects_non_repository_relative_paths(repo, file):
    cutoff = commit_files(repo, "Root", {"A.al": "root\n"})
    with pytest.raises(ValueError, match="repository-relative"):
        build_report(repo, "NAV", cutoff, [file])


@pytest.mark.parametrize("commit", ["HEAD", "main", "abc123", "a" * 40 + "^", "--all"])
def test_requires_full_commit_hash(repo, commit):
    with pytest.raises(ValueError, match="40-character"):
        build_report(repo, "NAV", commit, ["A.al"])


def test_rejects_directories_and_unknown_paths(repo):
    cutoff = commit_files(repo, "Root", {"App/A.al": "root\n"})
    with pytest.raises(ValueError, match="not a directory"):
        build_report(repo, "NAV", cutoff, ["App"])
    with pytest.raises(ValueError, match="File not found"):
        build_report(repo, "NAV", cutoff, ["missing.al"])


def test_rejects_invalid_label_empty_files_and_nonpositive_limit(repo):
    cutoff = commit_files(repo, "Root", {"A.al": "root\n"})
    with pytest.raises(ValueError, match="Unsupported repository"):
        build_report(repo, "Other", cutoff, ["A.al"])
    with pytest.raises(ValueError, match="agent-selected"):
        build_report(repo, "NAV", cutoff, [])
    with pytest.raises(ValueError, match="positive"):
        build_report(repo, "NAV", cutoff, ["A.al"], max_commits=0)
    with pytest.raises(ValueError, match="max-files"):
        build_report(repo, "NAV", cutoff, ["A.al"], max_files=0)


def test_cli_creates_report_only_on_request_and_refuses_overwrite(repo, remote, tmp_path, capsys):
    commit_files(repo, "Root", {"App/A.al": "root\n", "B.al": "root\n"})
    cutoff = commit_files(repo, "Cutoff", {"App/A.al": "cutoff\n"})
    output = tmp_path / "reports" / "history.md"
    args = ["--repo", "NAV", "--commit", cutoff, "--file", r"App\A.al", "--file", "B.al", "--output", str(output)]

    main(args)

    original = output.read_text(encoding="utf-8")
    assert "Historical change report" in original
    assert "History report written" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert "Output already exists" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == original


def test_missing_commit_fails_without_output(repo, remote, tmp_path, capsys):
    commit_files(repo, "Root", {"A.al": "root\n"})
    output = tmp_path / "history.md"
    with pytest.raises(SystemExit) as error:
        main(["--repo", "NAV", "--commit", "0" * 40, "--file", "A.al", "--output", str(output)])
    assert error.value.code == 2
    assert "Remote history/authentication command failed" in capsys.readouterr().err
    assert not output.exists()


def test_working_tree_is_not_read_or_modified(repo):
    ancestor = commit_files(repo, "Original", {"A.al": "historical\n", "B.al": "original\n"})
    cutoff = commit_files(repo, "Cutoff", {"B.al": "cutoff\n"})
    (repo / "A.al").write_text("uncommitted candidate secret\n", encoding="utf-8")
    (repo / "Untracked.al").write_text("untracked secret\n", encoding="utf-8")
    before = git(repo, "status", "--porcelain")

    report = build_report(repo, "NAV", cutoff, ["A.al"])

    assert f"## Commit {ancestor}" in report
    assert "uncommitted candidate secret" not in report
    assert "untracked secret" not in report
    assert git(repo, "status", "--porcelain") == before
    assert (repo / "A.al").read_text(encoding="utf-8") == "uncommitted candidate secret\n"


def test_cli_rejects_non_markdown_output(repo, tmp_path, capsys):
    cutoff = commit_files(repo, "Root", {"A.al": "root\n"})
    output = tmp_path / "history.al"
    with pytest.raises(SystemExit) as error:
        main(["--repo", "NAV", "--commit", cutoff, "--file", "A.al", "--output", str(output)])
    assert error.value.code == 2
    assert ".md extension" in capsys.readouterr().err
    assert not output.exists()


def test_standalone_script_needs_no_bcbench_import():
    script = Path(__file__).resolve().parents[1] / "tools" / "generate_history_report.py"
    result = subprocess.run([sys.executable, "-I", str(script), "--help"], capture_output=True, text=True, check=True)
    assert "--file" in result.stdout
    assert "--commit" in result.stdout
    assert "--repo-path" not in result.stdout
    assert "--max-files" in result.stdout


def test_default_limit_shows_first_ten_modified_names_and_lists_every_file(repo):
    names = [f"File{index:02d}.al" for index in range(12)]
    commit_files(repo, "Initial files", dict.fromkeys(names, "old\n"))
    commit_files(repo, "Modify twelve files", {name: f"new-content-{index:02d}\n" for index, name in enumerate(names)})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, [names[-1]], max_commits=1)

    assert len(re.findall(r"^diff --git ", report, re.MULTILINE)) == 10
    assert "10 of 12 distinct modified filenames (limit 10)" in report
    for index, name in enumerate(names):
        assert name in report
        if index < 10:
            assert f"+new-content-{index:02d}" in report
        else:
            assert f"+new-content-{index:02d}" not in report
            assert f"M\t{name}\t[content omitted]" in report


@pytest.mark.parametrize(
    ("requested", "representative"),
    [
        ("Locales/DK/foo.AL", "Locales/DK/foo.AL"),
        ("Locales/W1/Foo.al", "Locales/W1/Foo.al"),
        ("Locales/W1/Other.al", "Locales/W1/Foo.al"),
    ],
)
def test_localization_copies_count_once_and_prefer_requested_path_then_w1(repo, requested, representative):
    names = ["Locales/AT/Foo.al", "Locales/DK/foo.AL", "Locales/W1/Foo.al", "Locales/W1/Other.al"]
    commit_files(repo, "Initial files", dict.fromkeys(names, "old\n"))
    commit_files(repo, "Propagate change", {name: f"content-for-{name}\n" for name in names})
    cutoff = commit_files(repo, "Cutoff", {"Unrelated.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, [requested], max_commits=1, max_files=1)

    assert len(re.findall(r"^diff --git ", report, re.MULTILINE)) == 1
    assert "1 of 2 distinct modified filenames (limit 1)" in report
    for name in names:
        assert name in report
        assert (f"+content-for-{name}" in report) == (name == representative)


def test_localization_copies_do_not_consume_slots_for_other_names(repo):
    names = ["AT/A.al", "DK/A.al", "W1/A.al", "W1/B.al", "W1/C.al"]
    commit_files(repo, "Initial files", dict.fromkeys(names, "old\n"))
    commit_files(repo, "Modify", {name: f"new-{name}\n" for name in names})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["W1/A.al"], max_commits=1, max_files=2)

    assert len(re.findall(r"^diff --git ", report, re.MULTILINE)) == 2
    assert "+new-W1/A.al" in report
    assert "+new-W1/B.al" in report
    assert "+new-W1/C.al" not in report
    assert "+new-AT/A.al" not in report
    assert "+new-DK/A.al" not in report


def test_added_deleted_and_moved_files_are_metadata_only_and_do_not_consume_limit(repo):
    commit_files(
        repo,
        "Initial",
        {"BDeleted.al": "deleted-payload-must-not-appear\n", "Old/CMoved.al": "moved-payload-must-not-appear\n", "ZModified.al": "old\n"},
    )
    git(repo, "rm", "BDeleted.al")
    (repo / "New").mkdir()
    git(repo, "mv", "Old/CMoved.al", "New/CMoved.al")
    commit_files(repo, "Change files", {"AAdded.al": "added-payload-must-not-appear\n", "ZModified.al": "allowed-modification\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["ZModified.al"], max_commits=1, max_files=1)

    assert "A\tAAdded.al\t[content omitted]" in report
    assert "D\tBDeleted.al\t[content omitted]" in report
    assert "R100\tOld/CMoved.al -> New/CMoved.al\t[content omitted]" in report
    assert "1 of 1 distinct modified filenames" in report
    assert "+allowed-modification" in report
    assert "added-payload-must-not-appear" not in report
    assert "deleted-payload-must-not-appear" not in report
    assert "moved-payload-must-not-appear" not in report
    assert len(re.findall(r"^diff --git ", report, re.MULTILINE)) == 1


def test_renamed_file_with_content_changes_is_still_metadata_only(repo):
    content = "".join(f"rename-original-line-{index}\n" for index in range(30))
    commit_files(repo, "Initial", {"Old.al": content})
    git(repo, "mv", "Old.al", "Renamed.al")
    renamed = commit_files(repo, "Rename and modify", {"Renamed.al": content + "renamed-addition-must-not-appear\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["Renamed.al"], max_commits=1)

    assert f"## Commit {renamed}" in report
    assert re.search(r"R\d+\tOld.al -> Renamed.al\t\[content omitted\]", report)
    assert "metadata-only" in report
    assert "rename-original-line" not in report
    assert "renamed-addition-must-not-appear" not in report
    assert "diff --git" not in report


def test_limit_applies_independently_to_each_commit(repo):
    names = ["A.al", "B.al"]
    commit_files(repo, "Initial", dict.fromkeys(names, "old\n"))
    commit_files(repo, "First", dict.fromkeys(names, "first\n"))
    commit_files(repo, "Second", dict.fromkeys(names, "second\n"))
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})

    report = build_report(repo, "NAV", cutoff, ["A.al"], max_commits=2, max_files=1)

    assert report.count("1 of 2 distinct modified filenames (limit 1)") == 2
    assert len(re.findall(r"^diff --git ", report, re.MULTILINE)) == 2


def test_remote_cli_honors_file_limit(repo, remote, tmp_path):
    commit_files(repo, "Initial", {"A.al": "old\n", "B.al": "old\n"})
    commit_files(repo, "Modify", {"A.al": "allowed\n", "B.al": "omitted-body\n"})
    cutoff = commit_files(repo, "Cutoff", {"Other.al": "cutoff\n"})
    output = tmp_path / "limited.md"

    main(["--repo", "NAV", "--commit", cutoff, "--file", "A.al", "--max-commits", "1", "--max-files", "1", "--output", str(output)])

    report = output.read_text(encoding="utf-8")
    assert "+allowed" in report
    assert "B.al" in report
    assert "omitted-body" not in report


def test_remote_fetch_uses_only_cutoff_and_cleans_temporary_repository(repo, remote, monkeypatch):
    ancestor = commit_files(repo, "Ancestor", {"A.al": "historical\n", "Sibling.al": "co-change\n"})
    cutoff = commit_files(repo, "Cutoff secret", {"A.al": "cutoff secret\n"})
    future = commit_files(repo, "Future secret", {"A.al": "future secret\n"})
    calls = []
    run = history.GitRepository.run

    def record_run(self, *args):
        calls.append((self.path, args))
        return run(self, *args)

    monkeypatch.setattr(history.GitRepository, "run", record_run)
    report = history.build_remote_report(["NAV"], {"NAV": cutoff}, {"NAV": ["A.al"]})

    assert f"## Commit {ancestor}" in report
    assert "Sibling.al" in report
    assert "Cutoff secret" not in report
    assert "Future secret" not in report
    assert future not in report
    assert [args for _, args in calls if args[0] == "fetch"] == [("fetch", "--no-tags", "--depth=200", "--filter=blob:none", "origin", cutoff)]
    assert all(not path.exists() for path, _ in calls)
    assert not any(args[0] == "checkout" for _, args in calls)
    assert git(repo, "rev-parse", "HEAD") == future


def test_multi_repo_report_requires_and_respects_independent_cutoffs(repo, remote, tmp_path, monkeypatch):
    nav_ancestor = commit_files(repo, "NAV history", {"App/A.al": "nav\n"})
    nav_cutoff = commit_files(repo, "NAV cutoff", {"App/A.al": "nav cutoff\n"})
    bcapps = tmp_path / "bcapps"
    bcapps.mkdir()
    git(bcapps, "init", "-b", "main")
    git(bcapps, "config", "user.name", "History Test")
    git(bcapps, "config", "user.email", "history@example.invalid")
    git(bcapps, "config", "commit.gpgsign", "false")
    bcapps_ancestor = commit_files(bcapps, "BCApps history", {"src/A.al": "bcapps\n"})
    bcapps_cutoff = commit_files(bcapps, "BCApps cutoff", {"src/A.al": "bcapps cutoff\n"})
    commit_files(bcapps, "BCApps future secret", {"src/A.al": "bcapps future\n"})
    monkeypatch.setitem(history.REPOSITORIES, "BCApps", bcapps.as_uri())
    output = tmp_path / "both.md"

    main(
        [
            "--repo",
            "NAV",
            "BCApps",
            "--commit",
            f"NAV={nav_cutoff}",
            "--commit",
            f"BCApps={bcapps_cutoff}",
            "--file",
            r"NAV=App\A.al",
            "--file",
            r"BCApps=src\A.al",
            "--output",
            str(output),
        ]
    )

    report = output.read_text(encoding="utf-8")
    assert "Repository: **NAV**" in report
    assert "Repository: **BCApps**" in report
    assert f"## Commit {nav_ancestor}" in report
    assert f"## Commit {bcapps_ancestor}" in report
    assert "BCApps future secret" not in report
    assert "Local clone:" not in report


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--repo", "NAV", "BCApps", "--commit", "a" * 40, "--file", "NAV=A.al"], "REPO=value"),
        (["--repo", "NAV", "BCApps", "--commit", "NAV=" + "a" * 40, "--file", "NAV=A.al"], "own cutoff SHA"),
        (["--repo", "NAV", "--commit", "a" * 40, "--commit", "b" * 40, "--file", "A.al"], "exactly one"),
        (["--repo", "NAV", "--commit", "a" * 40, "--file", "BCApps=A.al"], "selected repository"),
        (["--repo", "NAV", "--commit", "a" * 40, "--file", "../A.al"], "repository-relative"),
        (["--repo", "NAV", "--commit", "a" * 40, "--file", "A.al", "--history-depth", "0"], "positive"),
        (["--repo", "NAV", "--commit", "a" * 40, "--file", "A.al", "--max-files", "0"], "max-files"),
    ],
)
def test_cli_rejects_ambiguous_remote_requests_before_network(args, message, tmp_path, capsys, monkeypatch):
    def no_credentials(_):
        pytest.fail("Invalid request must not start remote access")

    monkeypatch.setattr(history, "_remote_environment", no_credentials)
    output = tmp_path / "report.md"
    with pytest.raises(SystemExit) as error:
        main([*args, "--output", str(output)])
    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert not output.exists()


def test_remote_failure_does_not_emit_partial_multi_repo_report(repo, remote, tmp_path, monkeypatch, capsys):
    commit_files(repo, "NAV history", {"A.al": "nav\n"})
    cutoff = commit_files(repo, "Cutoff", {"A.al": "cutoff\n"})
    monkeypatch.setitem(history.REPOSITORIES, "BCApps", (tmp_path / "missing-remote").as_uri())
    output = tmp_path / "report.md"
    with pytest.raises(SystemExit):
        main(
            [
                "--repo",
                "NAV",
                "BCApps",
                "--commit",
                f"NAV={cutoff}",
                "--commit",
                "BCApps=" + "a" * 40,
                "--file",
                "NAV=A.al",
                "--file",
                "BCApps=A.al",
                "--output",
                str(output),
            ]
        )
    assert "Remote history/authentication command failed" in capsys.readouterr().err
    assert not output.exists()


def test_nav_token_is_scoped_to_remote_and_not_persisted_in_git_config(repo, monkeypatch):
    monkeypatch.setenv("ADO_TOKEN", "test-only-token")
    environment = history._remote_environment("NAV")
    assert environment["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer test-only-token"
    assert environment["GIT_CONFIG_KEY_0"] == f"http.{history.REPOSITORIES['NAV']}.extraHeader"
    reader = history.GitRepository(repo, environment)
    assert reader.run("config", "--get", environment["GIT_CONFIG_KEY_0"]).strip() == environment["GIT_CONFIG_VALUE_0"]
    assert "test-only-token" not in (repo / ".git" / "config").read_text(encoding="utf-8")
    assert "test-only-token" not in repr(reader)


def test_public_bcapps_can_use_anonymous_access(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert history._remote_environment("BCApps") == {"GIT_NO_LAZY_FETCH": "0"}


def test_nav_pat_authentication(monkeypatch):
    monkeypatch.delenv("ADO_TOKEN", raising=False)
    monkeypatch.setenv("AZURE_DEVOPS_EXT_PAT", "test-only-pat")
    environment = history._remote_environment("NAV")
    assert environment["GIT_CONFIG_VALUE_0"] == "Authorization: Basic OnRlc3Qtb25seS1wYXQ="


def test_nav_azure_cli_login_is_used_when_no_token_is_supplied(monkeypatch):
    monkeypatch.delenv("ADO_TOKEN", raising=False)
    monkeypatch.delenv("AZURE_DEVOPS_EXT_PAT", raising=False)
    calls = []

    def token_command(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="test-only-entra-token\n")

    monkeypatch.setattr(history.subprocess, "run", token_command)
    environment = history._remote_environment("NAV")
    assert calls == [["az", "account", "get-access-token", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--query", "accessToken", "--output", "tsv"]]
    assert environment["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer test-only-entra-token"
