from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput, analyze_generated_bugfix_output
from bcbench.exceptions import GeneratedOutputError, NoTestsExtractedError, ProjectDiscoveryError


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

    result = analyze_generated_bugfix_output(repo_path, generated_patch)

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

    result = analyze_generated_bugfix_output(repo_path, generated_patch)

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

    with pytest.raises(GeneratedOutputError, match=r"Agent produced tests but no product-code fix\."):
        analyze_generated_bugfix_output(repo_path, generated_patch)


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

    with pytest.raises(NoTestsExtractedError):
        analyze_generated_bugfix_output(repo_path, generated_patch)


def test_propagates_project_discovery_error_for_file_without_app_json(tmp_path: Path):
    repo_path = tmp_path / "repo"
    _write_file(repo_path, "src/Unknown/Feature.al", "table 50100 Feature {}\n")
    generated_patch = _patch("src/Unknown/Feature.al", "table 50100 Feature {}", ["// Fix"])

    with pytest.raises(ProjectDiscoveryError, match=r"No owning app\.json found"):
        analyze_generated_bugfix_output(repo_path, generated_patch)


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

    result = analyze_generated_bugfix_output(repo_path, generated_patch)

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
            content = f"{first_line}\n{{\n    [Test]\n    procedure {name}()\n    begin\n    end;\n}}\n"
        else:
            content = f"{first_line}\n"
        _write_file(repo_path, file_path, content)
    generated_patch = (
        _patch("src/tests/Zeta/ZetaTests.Codeunit.al", files["src/tests/Zeta/ZetaTests.Codeunit.al"], ["{", "    [Test]", "    procedure TestsZeta()", "}"])
        + _patch("src/Zeta/Zeta.Table.al", files["src/Zeta/Zeta.Table.al"], ["// Fix Zeta"])
        + _patch("src/tests/Alpha/AlphaTests.Codeunit.al", files["src/tests/Alpha/AlphaTests.Codeunit.al"], ["{", "    [Test]", "    procedure TestsAlpha()", "}"])
        + _patch("src/Alpha/Alpha.Table.al", files["src/Alpha/Alpha.Table.al"], ["// Fix Alpha"])
    )

    result = analyze_generated_bugfix_output(repo_path, generated_patch)

    assert result.app_projects == (
        str(app_alpha.relative_to(repo_path)),
        str(app_zeta.relative_to(repo_path)),
    )
    assert result.test_projects == (
        str(test_alpha.relative_to(repo_path)),
        str(test_zeta.relative_to(repo_path)),
    )
