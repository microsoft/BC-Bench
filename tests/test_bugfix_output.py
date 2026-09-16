import subprocess
from collections.abc import Iterable
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from unidiff.errors import UnidiffParseError

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.evaluate.bugfix_output import analyze_generated_bugfix_output as _analyze_generated_bugfix_output
from bcbench.exceptions import GeneratedOutputError, GeneratedSubmissionError, NoTestsExtractedError, ProjectDiscoveryError


def _create_project(repo_path: Path, project_path: str) -> Path:
    project = repo_path / project_path
    project.mkdir(parents=True)
    (project / "app.json").write_text("{}", encoding="utf-8")
    return project


def _write_file(repo_path: Path, file_path: str, content: str) -> None:
    path = repo_path / file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)


def _trusted_commit(repo_path: Path) -> str:
    repo_path.mkdir(parents=True, exist_ok=True)
    head_result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if head_result.returncode == 0:
        return head_result.stdout.strip()

    if not (repo_path / ".git").exists():
        _init_git_repo(repo_path)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "Trusted baseline"], cwd=repo_path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def analyze_generated_bugfix_output(
    repo_path: Path,
    generated_patch: str,
    allowed_app_projects: Iterable[str] = (),
) -> GeneratedBugFixOutput:
    return _analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        _trusted_commit(repo_path),
        allowed_app_projects,
    )


def _commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial"], cwd=repo_path, check=True)


def _git_diff(repo_path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "diff", "--no-ext-diff", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _real_git_rename_submission(repo_path: Path, product_project: str, decoy_project: str | None = None) -> str:
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, product_project)
    _create_project(repo_path, "Tests")
    if decoy_project is not None:
        _create_project(repo_path, decoy_project)

    source_file = repo_path / product_project / "OldFeature.Codeunit.al"
    target_file = repo_path / product_project / "NewFeature.Codeunit.al"
    test_file = repo_path / "Tests" / "FeatureTests.Codeunit.al"
    source_file.write_text("codeunit 50100 Feature {}\n", encoding="utf-8")
    test_file.write_text("codeunit 50101 FeatureTests\n{\n}\n", encoding="utf-8")
    _commit_all(repo_path)

    source_file.rename(target_file)
    test_file.write_text(
        "codeunit 50101 FeatureTests\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    return _git_diff(repo_path, "--cached", "--find-renames=100%")


def _patch(file_path: str, old_line: str, added_lines: list[str]) -> str:
    additions = "\n".join(f"+{line}" for line in added_lines)
    return f"diff --git a/{file_path} b/{file_path}\nindex 1111111..2222222 100644\n--- a/{file_path}\n+++ b/{file_path}\n@@ -1,1 +1,{len(added_lines) + 1} @@\n {old_line}\n{additions}\n"


def _rename_patch(source_path: str, target_path: str) -> str:
    return f"diff --git a/{source_path} b/{target_path}\nsimilarity index 100%\nrename from {source_path}\nrename to {target_path}\n"


def _new_file_patch(file_path: str) -> str:
    return f"diff --git a/{file_path} b/{file_path}\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n+++ b/{file_path}\n@@ -0,0 +1 @@\n+codeunit 50100 Feature {{}}\n"


def _deleted_file_patch(file_path: str) -> str:
    return f"diff --git a/{file_path} b/{file_path}\ndeleted file mode 100644\nindex 1111111..0000000\n--- a/{file_path}\n+++ /dev/null\n@@ -1 +0,0 @@\n-codeunit 50100 Feature {{}}\n"


def test_analyzes_base_app_fix_and_scm_manufacturing_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    app_project = _create_project(repo_path, "App/Layers/W1/BaseApp")
    test_project = _create_project(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing")
    product_file = "App/Layers/W1/BaseApp/Item.Table.al"
    test_file = "App/Layers/W1/Tests/SCM-Manufacturing/ProductionOrder.Codeunit.al"
    _write_file(repo_path, product_file, "table 27 Item {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 137310 "Production Order Tests"\n{\n    [Test]\n    procedure ReplansProductionOrder()\n    begin\n    end;\n}\n',
    )
    fix_patch = _patch(product_file, "table 27 Item {}", ["// Product fix"])
    test_patch = _patch(
        test_file,
        'codeunit 137310 "Production Order Tests"',
        ["{", "    [Test]", "    procedure ReplansProductionOrder()", "    begin", "    end;", "}"],
    )
    generated_patch = fix_patch + test_patch

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=["App/Layers/W1/BaseApp"],
    )

    assert isinstance(result, GeneratedBugFixOutput)
    assert result.full_patch == generated_patch
    assert result.fix_patch == fix_patch
    assert result.test_patch == test_patch
    assert result.app_projects == (str(app_project.relative_to(repo_path)),)
    assert result.test_projects == (str(test_project.relative_to(repo_path)),)
    assert result.tests == (TestEntry(codeunitID=137310, functionName=frozenset({"ReplansProductionOrder"})),)
    field_name = "full_patch"
    with pytest.raises(FrozenInstanceError):
        setattr(result, field_name, "")


def test_discovers_generated_test_project_without_dataset_paths(tmp_path: Path):
    repo_path = tmp_path / "repo"
    app_project = _create_project(repo_path, "src/Main")
    test_project = _create_project(repo_path, "extensions/Quality/test")
    product_file = "src/Main/Feature.Codeunit.al"
    test_file = "extensions/Quality/test/FeatureTests.Codeunit.al"
    _write_file(repo_path, product_file, "codeunit 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    generated_patch = _patch(product_file, "codeunit 50100 Feature {}", ["// Fix"]) + _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=["src/Main"],
    )

    assert result.app_projects == (str(app_project.relative_to(repo_path)),)
    assert result.test_projects == (str(test_project.relative_to(repo_path)),)


def test_rejects_test_only_patch(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/App/test")
    test_file = "src/App/test/FeatureTests.Codeunit.al"
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    generated_patch = _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Agent produced tests but no product-code fix\."):
        analyze_generated_bugfix_output(repo_path, generated_patch, allowed_app_projects=[])


def test_rejects_fix_without_new_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Main/test")
    product_file = "src/Main/Feature.Codeunit.al"
    test_file = "src/Main/test/FeatureTests.Codeunit.al"
    _write_file(repo_path, product_file, "codeunit 50100 Feature {}\n")
    _write_file(repo_path, test_file, 'codeunit 50101 "Feature Tests" {}\n')
    generated_patch = _patch(product_file, "codeunit 50100 Feature {}", ["// Fix"]) + _patch(
        test_file,
        'codeunit 50101 "Feature Tests" {}',
        ["// Refactor without a new test"],
    )

    with pytest.raises(GeneratedSubmissionError, match=r"No tests extracted from the generated patch\.") as exc_info:
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Main"],
        )

    assert isinstance(exc_info.value.__cause__, NoTestsExtractedError)


def test_wraps_project_discovery_error_for_file_without_app_json(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _write_file(repo_path, "src/Unknown/Feature.al", "table 50100 Feature {}\n")
    generated_patch = _patch("src/Unknown/Feature.al", "table 50100 Feature {}", ["// Fix"])

    with pytest.raises(GeneratedSubmissionError, match=r"No owning app\.json found") as exc_info:
        analyze_generated_bugfix_output(repo_path, generated_patch, allowed_app_projects=[])

    assert isinstance(exc_info.value.__cause__, ProjectDiscoveryError)


def test_deduplicates_multiple_files_in_one_project(tmp_path: Path):
    repo_path = tmp_path / "repo"
    app_project = _create_project(repo_path, "src/Main")
    test_project = _create_project(repo_path, "src/Main/test")
    product_files = ["src/Main/Feature.Table.al", "src/Main/Feature.Codeunit.al"]
    test_file = "src/Main/test/FeatureTests.Codeunit.al"
    for product_file in product_files:
        _write_file(repo_path, product_file, "table 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    generated_patch = "".join(_patch(product_file, "table 50100 Feature {}", ["// Fix"]) for product_file in product_files) + _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=["src/Main"],
    )

    assert result.app_projects == (str(app_project.relative_to(repo_path)),)
    assert result.test_projects == (str(test_project.relative_to(repo_path)),)


def test_returns_multiple_projects_in_deterministic_order(tmp_path: Path):
    repo_path = tmp_path / "repo"
    app_zeta = _create_project(repo_path, "src/Zeta")
    app_alpha = _create_project(repo_path, "src/Alpha")
    test_zeta = _create_project(repo_path, "src/tests/Zeta")
    test_alpha = _create_project(repo_path, "src/tests/Alpha")
    files = {
        "src/Zeta/Zeta.Table.al": "table 50100 Zeta {}",
        "src/Alpha/Alpha.Table.al": "table 50101 Alpha {}",
        "src/tests/Zeta/ZetaTests.Codeunit.al": 'codeunit 50102 "Zeta Tests"',
        "src/tests/Alpha/AlphaTests.Codeunit.al": 'codeunit 50103 "Alpha Tests"',
    }
    for file_path, first_line in files.items():
        if file_path.endswith("Tests.Codeunit.al"):
            name = "TestsZeta" if "Zeta" in file_path else "TestsAlpha"
            attribute = "    [Test]\n" if "Zeta" in file_path else ""
            content = f"{first_line}\n{{\n{attribute}    procedure {name}()\n    begin\n    end;\n}}\n"
        else:
            content = f"{first_line}\n"
        _write_file(repo_path, file_path, content)
    generated_patch = (
        _patch("src/tests/Zeta/ZetaTests.Codeunit.al", files["src/tests/Zeta/ZetaTests.Codeunit.al"], ["{", "    [Test]", "    procedure TestsZeta()", "}"])
        + _patch("src/Zeta/Zeta.Table.al", files["src/Zeta/Zeta.Table.al"], ["// Fix Zeta"])
        + _patch("src/tests/Alpha/AlphaTests.Codeunit.al", files["src/tests/Alpha/AlphaTests.Codeunit.al"], ["{", "    procedure TestsAlpha()", "}"])
        + _patch("src/Alpha/Alpha.Table.al", files["src/Alpha/Alpha.Table.al"], ["// Fix Alpha"])
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=["src/Zeta", "src/Alpha"],
    )

    assert result.app_projects == (
        str(app_alpha.relative_to(repo_path)),
        str(app_zeta.relative_to(repo_path)),
    )
    assert result.test_projects == (
        str(test_alpha.relative_to(repo_path)),
        str(test_zeta.relative_to(repo_path)),
    )


def test_same_class_cross_project_rename_touches_both_projects(tmp_path: Path):
    repo_path = tmp_path / "repo"
    source_project = _create_project(repo_path, "src/Source")
    target_project = _create_project(repo_path, "src/Target")
    test_project = _create_project(repo_path, "src/Tests")
    source_file = "src/Source/Feature.Codeunit.al"
    target_file = "src/Target/Feature.Codeunit.al"
    test_file = "src/Tests/FeatureTests.Codeunit.al"
    _write_file(repo_path, target_file, "codeunit 50100 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    rename_patch = _rename_patch(source_file, target_file)
    test_patch = _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        rename_patch + test_patch,
        allowed_app_projects=["src/Source", "src/Target"],
    )

    assert result.fix_patch == rename_patch
    assert result.test_patch == test_patch
    assert result.app_projects == (
        str(source_project.relative_to(repo_path)),
        str(target_project.relative_to(repo_path)),
    )
    assert result.test_projects == (str(test_project.relative_to(repo_path)),)


@pytest.mark.parametrize(
    ("fix_patch", "mode_line"),
    [
        (_new_file_patch("src/Main/Feature.Codeunit.al"), "new file mode 100644"),
        (_deleted_file_patch("src/Main/Feature.Codeunit.al"), "deleted file mode 100644"),
    ],
)
def test_preserves_valid_new_and_deleted_al_text_diffs(tmp_path: Path, fix_patch: str, mode_line: str):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    test_file = "src/Tests/FeatureTests.Codeunit.al"
    _write_file(
        repo_path,
        test_file,
        'codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n',
    )
    test_patch = _patch(
        test_file,
        'codeunit 50101 "Feature Tests"',
        ["{", "    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;", "}"],
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        fix_patch + test_patch,
        allowed_app_projects=["src/Main"],
    )

    assert mode_line in result.fix_patch
    assert result.test_patch == test_patch


def test_rejects_real_binary_al_git_diff_as_invalid_submission(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    project_path = _create_project(repo_path, "src/Main")
    binary_file = project_path / "Binary.Codeunit.al"
    binary_file.write_bytes(b"\x00\x01\x02\x03")
    _commit_all(repo_path)
    binary_file.write_bytes(b"\x00\x01\x02\x04")
    generated_patch = _git_diff(repo_path, "--binary", "--", "src/Main/Binary.Codeunit.al")

    assert "GIT binary patch" in generated_patch
    with pytest.raises(GeneratedSubmissionError, match=r"Binary AL changes are not allowed"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Main"],
        )


@pytest.mark.parametrize(
    "generated_patch",
    [
        (
            "diff --git a/src/Main/Binary.Codeunit.al b/src/Main/Binary.Codeunit.al\n"
            "index 1111111..2222222 100644\n"
            "Binary files a/src/Main/Binary.Codeunit.al and b/src/Main/Binary.Codeunit.al differ\n"
        ),
        ("diff --git a/src/Main/Binary.Codeunit.al b/src/Main/Binary.Codeunit.al\nold mode 100644\nnew mode 100755\n"),
    ],
)
def test_rejects_binary_metadata_and_mode_only_entries_before_hunk_validation(tmp_path: Path, generated_patch: str):
    error_pattern = r"(Binary AL|Mode-only AL) changes are not allowed"

    with pytest.raises(GeneratedSubmissionError, match=error_pattern):
        analyze_generated_bugfix_output(
            tmp_path,
            generated_patch,
            allowed_app_projects=[],
        )


def test_accepts_real_git_test_path_with_component_ending_in_b(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    app_project = _create_project(repo_path, "src/Main")
    test_project = _create_project(repo_path, "Tests")
    product_file = app_project / "Feature.Codeunit.al"
    test_file = test_project / "foo b" / "bar" / "F.Codeunit.al"
    test_file.parent.mkdir(parents=True)
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text("codeunit 2 FeatureTests\n{\n}\n", encoding="utf-8")
    _commit_all(repo_path)
    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [tEsT]\n    procedure VerifiesFeature()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    generated_patch = _git_diff(repo_path)

    assert "a/Tests/foo b/bar/F.Codeunit.al b/Tests/foo b/bar/F.Codeunit.al" in generated_patch
    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=["src/Main"],
    )

    assert result.full_patch == generated_patch
    assert result.app_projects == (str(app_project.relative_to(repo_path)),)
    assert result.test_projects == (str(test_project.relative_to(repo_path)),)
    assert result.tests == (TestEntry(codeunitID=2, functionName=frozenset({"VerifiesFeature"})),)
    assert "Tests/foo b/bar/F.Codeunit.al" in result.test_patch


@pytest.mark.parametrize("literal_root", ["a", "b"])
def test_rejects_real_git_pure_rename_remapped_to_allowlisted_decoy(tmp_path: Path, literal_root: str):
    repo_path = tmp_path / "repo"
    product_project = f"{literal_root}/Main"
    generated_patch = _real_git_rename_submission(repo_path, product_project, decoy_project="Main")

    assert f"rename from {product_project}/OldFeature.Codeunit.al" in generated_patch
    assert f"rename to {product_project}/NewFeature.Codeunit.al" in generated_patch
    with pytest.raises(GeneratedSubmissionError, match=rf"Product project is not allowed: {literal_root}.Main"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["Main"],
        )


def test_accepts_real_git_pure_rename_in_allowlisted_project(tmp_path: Path):
    repo_path = tmp_path / "repo"
    product_project = "src/Main"
    generated_patch = _real_git_rename_submission(repo_path, product_project)

    assert "rename from src/Main/OldFeature.Codeunit.al" in generated_patch
    assert "rename to src/Main/NewFeature.Codeunit.al" in generated_patch
    result = analyze_generated_bugfix_output(
        repo_path,
        generated_patch,
        allowed_app_projects=[product_project],
    )

    assert result.full_patch == generated_patch
    assert result.app_projects == (str((repo_path / product_project).relative_to(repo_path)),)
    assert result.tests == (TestEntry(codeunitID=50101, functionName=frozenset({"VerifiesFeature"})),)


def test_rejects_rename_between_product_and_test_projects(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    source_file = "src/Main/Feature.Codeunit.al"
    target_file = "src/Tests/Feature.Codeunit.al"
    _write_file(repo_path, target_file, "codeunit 50100 Feature {}\n")

    with pytest.raises(GeneratedSubmissionError, match=r"Cannot safely split rename.*src/Main/Feature\.Codeunit\.al.*src/Tests/Feature\.Codeunit\.al"):
        analyze_generated_bugfix_output(
            repo_path,
            _rename_patch(source_file, target_file),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_blank_patch(tmp_path: Path):
    with pytest.raises(GeneratedOutputError, match=r"Generated patch is blank\."):
        analyze_generated_bugfix_output(tmp_path, " \n\t", allowed_app_projects=[])


def test_rejects_header_only_diff(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    header_only_patch = "diff --git a/src/Main/Feature.al b/src/Main/Feature.al\n"

    with pytest.raises(GeneratedOutputError, match=r"Malformed generated patch:.*no hunks"):
        analyze_generated_bugfix_output(
            repo_path,
            header_only_patch,
            allowed_app_projects=["src/Main"],
        )


def test_rejects_nonblank_text_that_parses_to_no_files(tmp_path: Path):
    with pytest.raises(GeneratedOutputError, match=r"Malformed generated patch:.*no patched files"):
        analyze_generated_bugfix_output(tmp_path, "not a patch\n", allowed_app_projects=[])


def test_wraps_malformed_patch_error(tmp_path: Path):
    malformed_patch = "diff --git a/Feature.al b/Feature.al\n--- a/Feature.al\n+++ b/Feature.al\n@@ -1,2 +1,1 @@\n-old\n+new\n"

    with pytest.raises(GeneratedOutputError, match=r"Failed to parse generated patch") as exc_info:
        analyze_generated_bugfix_output(tmp_path, malformed_patch, allowed_app_projects=[])

    assert isinstance(exc_info.value.__cause__, UnidiffParseError)


def test_wraps_missing_codeunit_identity_as_invalid_submission(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = "src/Main/Feature.Codeunit.al"
    test_file = "src/Tests/FeatureTests.Codeunit.al"
    _write_file(repo_path, product_file, "codeunit 1 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        "procedure Helper()\n    [Test]\n    procedure VerifiesFeature()\n    begin\n    end;\n",
    )
    generated_patch = _patch(product_file, "codeunit 1 Feature {}", ["// Fix"]) + _patch(
        test_file,
        "procedure Helper()",
        ["    [Test]", "    procedure VerifiesFeature()", "    begin", "    end;"],
    )

    with pytest.raises(GeneratedSubmissionError, match=r"No codeunit ID found") as exc_info:
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Main"],
        )

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_does_not_wrap_unexpected_test_extraction_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = "src/Main/Feature.Codeunit.al"
    test_file = "src/Tests/FeatureTests.Codeunit.al"
    _write_file(repo_path, product_file, "codeunit 1 Feature {}\n")
    _write_file(repo_path, test_file, "codeunit 2 FeatureTests\n")
    generated_patch = _patch(product_file, "codeunit 1 Feature {}", ["// Fix"]) + _patch(
        test_file,
        "codeunit 2 FeatureTests",
        ["    [Test]", "    procedure VerifiesFeature()"],
    )

    def fail_extraction(*_args: object) -> None:
        raise RuntimeError("programmer error")

    monkeypatch.setattr("bcbench.evaluate.bugfix_output.extract_executable_member_occurrences_from_content", fail_extraction)

    with pytest.raises(RuntimeError, match="programmer error"):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Main"],
        )


def test_rejects_test_procedure_text_inside_block_comment(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text("codeunit 2 FeatureTests\n{\n}\n", encoding="utf-8")
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    /*\n    [Test]\n    procedure FakeTest()\n    begin\n    end;\n    */\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"No tests extracted from the generated patch\."):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_test_procedure_text_inside_line_comment_and_string(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text("codeunit 2 FeatureTests\n{\n}\n", encoding="utf-8")
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    // [Test]\n    // procedure LineCommentTest()\n    procedure Helper()\n    begin\n        Message('[Test] procedure StringTest()');\n    end;\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"No tests extracted from the generated patch\."):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_test_attribute_rebinding_to_inserted_procedure(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure InsertedTest()\n    begin\n    end;\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_accepts_one_new_test_in_existing_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n\n    [tEsT]\n    procedure NewTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        _git_diff(repo_path),
        allowed_app_projects=["src/Main"],
    )

    assert result.tests == (TestEntry(codeunitID=2, functionName=frozenset({"NewTest"})),)


@pytest.mark.parametrize(
    "existing_member",
    [
        "    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n",
        "    local procedure ExistingHelper()\n    begin\n    end;\n",
    ],
)
def test_rejects_added_undefined_conditional_wrapping_existing_test_member(tmp_path: Path, existing_member: str):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(f"codeunit 2 FeatureTests\n{{\n{existing_member}}}\n", encoding="utf-8")
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        f"codeunit 2 FeatureTests\n{{\n    #if UNDEFINED\n{existing_member}    #endif\n\n    [Test]\n    procedure NewTest()\n    begin\n    end;\n}}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Conditional compilation directives may not be added"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


@pytest.mark.parametrize("directive", ["#IF UNDEFINED", "    #elif UNDEFINED", "\t#elseif UNDEFINED", " #Else", "    #ENDIF"])
def test_rejects_added_conditional_compilation_directive_variant(tmp_path: Path, directive: str):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text("codeunit 2 FeatureTests\n{\n}\n", encoding="utf-8")
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        f"codeunit 2 FeatureTests\n{{\n{directive}\n    [Test]\n    procedure NewTest()\n    begin\n    end;\n}}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Conditional compilation directives may not be added"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_added_exit_inside_existing_test_with_one_new_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n        Assert.IsTrue(true, 'Expected');\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n        exit;\n        Assert.IsTrue(true, 'Expected');\n    end;\n\n    [Test]\n    procedure NewTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_added_attribute_attached_to_existing_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [HandlerFunctions('MessageHandler')]\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n\n    [Test]\n    procedure NewTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_added_statement_inside_existing_helper_called_by_new_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    local procedure ExistingHelper()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n"
        "    local procedure ExistingHelper()\n"
        "    begin\n"
        "        Message('Changed');\n"
        "    end;\n"
        "\n"
        "    [Test]\n"
        "    procedure NewTest()\n"
        "    begin\n"
        "        ExistingHelper();\n"
        "    end;\n"
        "}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_rejects_existing_helper_attribute_rebinding_to_new_helper(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Scope('OnPrem')]\n    local procedure ExistingHelper()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n"
        "    [Scope('OnPrem')]\n"
        "    local procedure NewHelper()\n"
        "    begin\n"
        "    end;\n"
        "\n"
        "    local procedure ExistingHelper()\n"
        "    begin\n"
        "    end;\n"
        "\n"
        "    [Test]\n"
        "    procedure NewTest()\n"
        "    begin\n"
        "        ExistingHelper();\n"
        "    end;\n"
        "}\n",
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


@pytest.mark.parametrize(
    "trigger_lines",
    [
        ["    trigger OnRun()", "    begin", "        Message('Changed');", "    end;"],
        ["    [TryFunction]", "    trigger OnRun()", "    begin", "    end;"],
    ],
)
def test_rejects_added_statement_or_attribute_on_existing_trigger(tmp_path: Path, trigger_lines: list[str]):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    trigger OnRun()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "\n".join(
            [
                "codeunit 2 FeatureTests",
                "{",
                *trigger_lines,
                "",
                "    [Test]",
                "    procedure NewTest()",
                "    begin",
                "    end;",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Existing test behavior modified"):
        analyze_generated_bugfix_output(
            repo_path,
            _git_diff(repo_path),
            allowed_app_projects=["src/Main"],
        )


def test_accepts_new_helper_outside_existing_test_and_one_new_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n\n    local procedure NewHelper()\n    begin\n    end;\n\n    [Test]\n    procedure NewTest()\n    begin\n        NewHelper();\n    end;\n}\n",
        encoding="utf-8",
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        _git_diff(repo_path),
        allowed_app_projects=["src/Main"],
    )

    assert result.tests == (TestEntry(codeunitID=2, functionName=frozenset({"NewTest"})),)


def test_accepts_new_test_appended_adjacent_to_existing_test(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/FeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure ExistingTest()\n    begin\n    end;\n    [Test]\n    procedure NewTest()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )

    result = analyze_generated_bugfix_output(
        repo_path,
        _git_diff(repo_path),
        allowed_app_projects=["src/Main"],
    )

    assert result.tests == (TestEntry(codeunitID=2, functionName=frozenset({"NewTest"})),)


def test_accepts_one_test_in_new_file(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = repo_path / "src/Main/Feature.Codeunit.al"
    test_file = repo_path / "src/Tests/NewFeatureTests.Codeunit.al"
    product_file.write_text("codeunit 1 Feature {}\n", encoding="utf-8")
    _commit_all(repo_path)

    product_file.write_text("codeunit 1 Feature {}\n// Fix\n", encoding="utf-8")
    test_file.write_text(
        'codeunit 3 "New Feature Tests"\n{\n    [Test]\n    procedure NewFileTest()\n    begin\n    end;\n}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-N", test_file], cwd=repo_path, check=True)

    result = analyze_generated_bugfix_output(
        repo_path,
        _git_diff(repo_path),
        allowed_app_projects=["src/Main"],
    )

    assert result.tests == (TestEntry(codeunitID=3, functionName=frozenset({"NewFileTest"})),)


def test_rejects_duplicate_identical_test_procedure_occurrences(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/Main")
    _create_project(repo_path, "src/Tests")
    product_file = "src/Main/Feature.Codeunit.al"
    test_file = "src/Tests/FeatureTests.Codeunit.al"
    _write_file(repo_path, product_file, "codeunit 1 Feature {}\n")
    _write_file(
        repo_path,
        test_file,
        "codeunit 2 FeatureTests\n{\n    [Test]\n    procedure SameTest()\n    begin\n    end;\n\n    [Test]\n    procedure SameTest()\n    begin\n    end;\n}\n",
    )
    generated_patch = _patch(product_file, "codeunit 1 Feature {}", ["// Fix"]) + _patch(
        test_file,
        "codeunit 2 FeatureTests",
        [
            "{",
            "    [Test]",
            "    procedure SameTest()",
            "    begin",
            "    end;",
            "",
            "    [Test]",
            "    procedure SameTest()",
            "    begin",
            "    end;",
            "}",
        ],
    )

    with pytest.raises(GeneratedSubmissionError, match=r"Expected exactly one new test procedure, found 2\."):
        analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            allowed_app_projects=["src/Main"],
        )
