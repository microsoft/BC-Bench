from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from unidiff.errors import UnidiffParseError

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput, analyze_generated_bugfix_output
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


def test_propagates_project_discovery_error_for_file_without_app_json(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _write_file(repo_path, "src/Unknown/Feature.al", "table 50100 Feature {}\n")
    generated_patch = _patch("src/Unknown/Feature.al", "table 50100 Feature {}", ["// Fix"])

    with pytest.raises(ProjectDiscoveryError, match=r"No owning app\.json found"):
        analyze_generated_bugfix_output(repo_path, generated_patch, allowed_app_projects=[])


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
