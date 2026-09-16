import subprocess
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_output import analyze_generated_bugfix_output
from bcbench.exceptions import EmptyDiffError, GeneratedSubmissionError
from bcbench.operations import stage_and_get_complete_diff


def _create_project(repo_path: Path, project_path: str) -> Path:
    project = repo_path / project_path
    project.mkdir(parents=True)
    (project / "app.json").write_text("{}", encoding="utf-8")
    return project


def _write_file(repo_path: Path, file_path: str, content: str) -> None:
    path = repo_path / file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _patch(file_path: str, old_line: str, added_lines: list[str]) -> str:
    additions = "\n".join(f"+{line}" for line in added_lines)
    return f"diff --git a/{file_path} b/{file_path}\nindex 1111111..2222222 100644\n--- a/{file_path}\n+++ b/{file_path}\n@@ -1,1 +1,{len(added_lines) + 1} @@\n {old_line}\n{additions}\n"


def _new_file_patch(file_path: str, added_lines: list[str]) -> str:
    additions = "\n".join(f"+{line}" for line in added_lines)
    return f"diff --git a/{file_path} b/{file_path}\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n+++ b/{file_path}\n@@ -0,0 +1,{len(added_lines)} @@\n{additions}\n"


def _deleted_file_patch(file_path: str, old_line: str) -> str:
    return f"diff --git a/{file_path} b/{file_path}\ndeleted file mode 100644\nindex 1111111..0000000\n--- a/{file_path}\n+++ /dev/null\n@@ -1 +0,0 @@\n-{old_line}\n"


def _rename_patch(source_path: str, target_path: str) -> str:
    return f"diff --git a/{source_path} b/{target_path}\nsimilarity index 100%\nrename from {source_path}\nrename to {target_path}\n"


def _valid_submission(repo_path: Path, test_project: str = "src/Tests") -> tuple[str, str, str]:
    product_project = "src/Main"
    product_file = f"{product_project}/Feature.Codeunit.al"
    test_file = f"{test_project}/FeatureTests.Codeunit.al"
    _create_project(repo_path, product_project)
    _create_project(repo_path, test_project)
    _write_file(repo_path, product_file, "codeunit 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    patch = _patch(product_file, "codeunit 50100 Feature {}", ["// Fix"]) + _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )
    return patch, product_project, test_project


def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)


def test_complete_diff_captures_al_and_manifest_changes(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _write_file(repo_path, "src/Main/Feature.al", "original\n")
    _write_file(repo_path, "src/Main/app.json", '{"name": "original"}\n')
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True)
    _write_file(repo_path, "src/Main/Feature.al", "modified\n")
    _write_file(repo_path, "src/Main/app.json", '{"name": "modified"}\n')

    diff = stage_and_get_complete_diff(repo_path)

    assert "src/Main/Feature.al" in diff
    assert "src/Main/app.json" in diff
    assert "+modified" in diff
    assert '+{"name": "modified"}' in diff


def test_complete_diff_rejects_empty_submission(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _write_file(repo_path, "README.md", "unchanged\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True)

    with pytest.raises(EmptyDiffError):
        stage_and_get_complete_diff(repo_path)


@pytest.mark.parametrize(
    "forbidden_path",
    [
        "src/Main/app.json",
        ".github/workflows/evaluate.yml",
        "README.md",
        "src/bcbench/evaluate/bugfix_output.py",
        ".bcbench/hidden-input.json",
        "pyproject.toml",
    ],
)
def test_rejects_non_al_changes(tmp_path: Path, forbidden_path: str):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, _ = _valid_submission(repo_path)
    generated_patch += _new_file_patch(forbidden_path, ["forbidden"])

    with pytest.raises(GeneratedSubmissionError, match=rf"Only AL files may be changed: {forbidden_path}"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[product_project],
        )


def test_rejects_product_project_outside_allowed_dataset_projects(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, _, _ = _valid_submission(repo_path)

    with pytest.raises(GeneratedSubmissionError, match=r"Product project is not allowed: src.Main"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Other"],
        )


def test_allows_test_project_absent_from_dataset_projects(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, test_project = _valid_submission(repo_path)

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=[product_project],
    )

    assert result.app_projects == (str((repo_path / product_project).relative_to(repo_path)),)
    assert result.test_projects == (str((repo_path / test_project).relative_to(repo_path)),)


def test_allows_root_test_project_absent_from_dataset_projects(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, test_project = _valid_submission(repo_path, test_project="Tests")

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=[product_project],
    )

    assert result.app_projects == (str((repo_path / product_project).relative_to(repo_path)),)
    assert result.test_projects == (str((repo_path / test_project).relative_to(repo_path)),)


@pytest.mark.parametrize("product_project", ["src/testing", "src/test-support"])
def test_rejects_product_project_with_test_prefix_outside_allowed_projects(tmp_path: Path, product_project: str):
    repo_path = tmp_path / "repo"
    generated_patch, allowed_product_project, _ = _valid_submission(repo_path, test_project=product_project)

    with pytest.raises(GeneratedSubmissionError) as exc_info:
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[allowed_product_project],
        )

    assert str(exc_info.value).replace("\\", "/") == f"Product project is not allowed: {product_project}"


def test_rejects_deleted_test_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, test_project = _valid_submission(repo_path)
    test_file = f"{test_project}/ObsoleteTests.Codeunit.al"
    _write_file(repo_path, test_file, "")
    generated_patch += _deleted_file_patch(test_file, 'codeunit 50102 "Obsolete Tests" {}')

    with pytest.raises(GeneratedSubmissionError, match=rf"Test files may not be deleted: {test_file}"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[product_project],
        )


def test_rejects_renamed_test_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, test_project = _valid_submission(repo_path)
    source_file = f"{test_project}/OldTests.Codeunit.al"
    target_file = f"{test_project}/NewTests.Codeunit.al"
    _write_file(repo_path, target_file, 'codeunit 50102 "New Tests" {}\n')
    generated_patch += _rename_patch(source_file, target_file)

    with pytest.raises(GeneratedSubmissionError, match=rf"Test files may not be renamed: {source_file} -> {target_file}"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[product_project],
        )


def test_rejects_removed_line_from_test_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    generated_patch, product_project, test_project = _valid_submission(repo_path)
    test_file = f"{test_project}/ExistingTests.Codeunit.al"
    _write_file(repo_path, test_file, 'codeunit 50102 "Existing Tests" {}\n')
    generated_patch += (
        f"diff --git a/{test_file} b/{test_file}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{test_file}\n"
        f"+++ b/{test_file}\n"
        "@@ -1 +1 @@\n"
        '-codeunit 50102 "Old Tests" {}\n'
        '+codeunit 50102 "Existing Tests" {}\n'
    )

    with pytest.raises(GeneratedSubmissionError, match=rf"Test changes may not remove lines: {test_file}"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[product_project],
        )


def test_allows_added_lines_in_existing_test_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    product_project = "src/Main"
    test_project = "src/Tests"
    product_file = f"{product_project}/Feature.Codeunit.al"
    test_file = f"{test_project}/FeatureTests.Codeunit.al"
    _create_project(repo_path, product_project)
    _create_project(repo_path, test_project)
    _write_file(repo_path, product_file, "codeunit 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    procedure Helper()\n    begin\n    end;\n\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    generated_patch = _patch(product_file, "codeunit 50100 Feature {}", ["// Fix"]) + _patch(
        test_file,
        "    procedure Helper()",
        ["", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;"],
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=[product_project],
    )

    assert result.test_projects == (str((repo_path / test_project).relative_to(repo_path)),)


def test_rejects_more_than_one_new_test_procedure(tmp_path: Path):
    repo_path = tmp_path / "repo"
    product_project = "src/Main"
    test_project = "src/Tests"
    product_file = f"{product_project}/Feature.Codeunit.al"
    test_file = f"{test_project}/FeatureTests.Codeunit.al"
    _create_project(repo_path, product_project)
    _create_project(repo_path, test_project)
    _write_file(repo_path, product_file, "codeunit 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure FirstTest()\n    begin\n    end;\n\n    [Test]\n    procedure SecondTest()\n    begin\n    end;\n}\n',
    )
    generated_patch = _patch(product_file, "codeunit 50100 Feature {}", ["// Fix"]) + _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        [
            "{",
            "    [Test]",
            "    procedure FirstTest()",
            "    begin",
            "    end;",
            "",
            "    [Test]",
            "    procedure SecondTest()",
            "    begin",
            "    end;",
            "}",
        ],
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Expected exactly one new test procedure, found 2\."):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=[product_project],
        )
