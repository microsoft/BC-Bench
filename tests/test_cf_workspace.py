"""Tests for counterfactual workspace extraction, patch regeneration, and entry creation."""

import json
from pathlib import Path

import pytest

from bcbench.dataset.cf_workspace import (
    _detect_fail_to_pass,
    _generate_git_diff,
    _next_cf_id,
    _reconstruct_padded_files,
    create_cf_entry,
    extract_workspace,
    regenerate_patches,
)
from bcbench.dataset.dataset_entry import TestEntry
from tests.conftest import create_dataset_entry

# A realistic AL patch for testing
SAMPLE_FIX_PATCH = """\
diff --git a/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al b/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
index 335c0099f4a..cf00000001 100644
--- a/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
+++ b/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
@@ -151,6 +151,8 @@ table 6217 "Sustainability Setup"
                 if Rec."Enable Value Chain Tracking" then
                     if not ConfirmManagement.GetResponseOrDefault(ConfirmEnableValueChainTrackingQst, false) then
                         Error('');
+
+                EnableEmissionsWhenValueChainTrackingIsEnabled();
             end;
         }
     }
"""

SAMPLE_TEST_PATCH = """\
diff --git a/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al b/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
index ff9b7640fa2..cf00000001 100644
--- a/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
+++ b/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
@@ -5123,6 +5123,22 @@ codeunit 148187 "Sust. Certificate Test"
         // [THEN] Confirmation Box should not pop up as there is no confirm Handler.
     end;

+    [Test]
+    [HandlerFunctions('ConfirmHandlerYes')]
+    procedure VerifyPurchDocEmissionsEnabled()
+    var
+        SustainabilitySetup: Record "Sustainability Setup";
+    begin
+        // [SCENARIO] Verify emissions enabled
+        LibrarySustainability.CleanUpBeforeTesting();
+        SustainabilitySetup.Get();
+        SustainabilitySetup.Validate("Enable Value Chain Tracking", true);
+        Assert.AreEqual(
+            true,
+            SustainabilitySetup."Use Emissions In Purch. Doc.",
+            'Should be enabled');
+    end;
+
     local procedure CreateSustainabilityAccount(var AccountCode: Code[20]; var CategoryCode: Code[20]; var SubcategoryCode: Code[20]; i: Integer): Record "Sustainability Account"
     begin
         CreateSustainabilitySubcategory(CategoryCode, SubcategoryCode, i);
"""


class TestReconstructPaddedFiles:
    def test_preserves_line_numbers_for_context(self):
        result = _reconstruct_padded_files(SAMPLE_FIX_PATCH)
        assert len(result) == 1

        path = "App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al"
        assert path in result

        before_lines, _after_lines = result[path]
        # Hunk starts at line 151, so we should have padding before that
        assert len(before_lines) >= 150  # at least up to the context

    def test_before_has_no_added_lines(self):
        result = _reconstruct_padded_files(SAMPLE_FIX_PATCH)
        path = "App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al"
        before_lines, _ = result[path]
        content = "".join(before_lines)
        assert "EnableEmissionsWhenValueChainTrackingIsEnabled" not in content

    def test_after_has_added_lines(self):
        result = _reconstruct_padded_files(SAMPLE_FIX_PATCH)
        path = "App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al"
        _, after_lines = result[path]
        content = "".join(after_lines)
        assert "EnableEmissionsWhenValueChainTrackingIsEnabled" in content

    def test_handles_test_patch_with_codeunit(self):
        result = _reconstruct_padded_files(SAMPLE_TEST_PATCH)
        path = "App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al"
        assert path in result
        before_lines, after_lines = result[path]
        assert len(after_lines) > len(before_lines)

    def test_empty_patch_returns_empty(self):
        result = _reconstruct_padded_files("")
        assert result == {}


class TestGenerateGitDiff:
    def test_generates_valid_diff_header(self):
        before = ["line1\n", "line2\n"]
        after = ["line1\n", "line2_modified\n"]
        diff = _generate_git_diff(before, after, "test.al")
        assert diff.startswith("diff --git a/test.al b/test.al\n")
        assert "--- a/test.al" in diff
        assert "+++ b/test.al" in diff

    def test_no_changes_returns_empty(self):
        lines = ["line1\n", "line2\n"]
        diff = _generate_git_diff(lines, lines, "test.al")
        assert diff == ""

    def test_added_lines_appear_in_diff(self):
        before = ["line1\n"]
        after = ["line1\n", "line2\n"]
        diff = _generate_git_diff(before, after, "test.al")
        assert "+line2\n" in diff


class TestExtractWorkspacePatchOnly:
    def test_creates_workspace_structure(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        assert (workspace / "workspace.json").exists()
        assert (workspace / "fix" / "before").is_dir()
        assert (workspace / "fix" / "after").is_dir()
        assert (workspace / "test" / "before").is_dir()
        assert (workspace / "test" / "after").is_dir()

    def test_metadata_contains_entry_info(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        metadata = json.loads((workspace / "workspace.json").read_text())
        assert metadata["entry_id"] == entry.instance_id
        assert metadata["mode"] == "patch-only"
        assert "fix" in metadata["files"]
        assert "test" in metadata["files"]

    def test_fix_files_are_extracted(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        fix_after = workspace / "fix" / "after" / "App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al"
        assert fix_after.exists()
        assert "EnableEmissionsWhenValueChainTrackingIsEnabled" in fix_after.read_text()

    def test_test_files_are_extracted(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        test_after = workspace / "test" / "after" / "App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al"
        assert test_after.exists()
        assert "VerifyPurchDocEmissionsEnabled" in test_after.read_text()


class TestRegeneratePatches:
    def test_round_trip_produces_diff(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        fix_patch, test_patch = regenerate_patches(workspace)
        assert "EnableEmissionsWhenValueChainTrackingIsEnabled" in fix_patch
        assert "VerifyPurchDocEmissionsEnabled" in test_patch

    def test_regenerated_patches_have_git_headers(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        fix_patch, test_patch = regenerate_patches(workspace)
        assert fix_patch.startswith("diff --git")
        assert test_patch.startswith("diff --git")

    def test_no_changes_produces_empty_patch(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        # Overwrite after with before content (no changes)
        fix_path = "App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al"
        before = (workspace / "fix" / "before" / fix_path).read_text()
        (workspace / "fix" / "after" / fix_path).write_text(before)

        fix_patch, _ = regenerate_patches(workspace)
        assert fix_patch == ""


class TestNextCfId:
    def test_first_cf_entry_is_cf_1(self, tmp_path: Path):
        cf_path = tmp_path / "counterfactual.jsonl"
        result = _next_cf_id("microsoftInternal__NAV-123456", cf_path)
        assert result == "microsoftInternal__NAV-123456__cf-1"

    def test_increments_from_existing(self, tmp_path: Path):
        cf_path = tmp_path / "counterfactual.jsonl"
        cf_path.write_text(json.dumps({"instance_id": "microsoftInternal__NAV-123456__cf-1"}) + "\n" + json.dumps({"instance_id": "microsoftInternal__NAV-123456__cf-2"}) + "\n")
        result = _next_cf_id("microsoftInternal__NAV-123456", cf_path)
        assert result == "microsoftInternal__NAV-123456__cf-3"

    def test_ignores_other_base_entries(self, tmp_path: Path):
        cf_path = tmp_path / "counterfactual.jsonl"
        cf_path.write_text(json.dumps({"instance_id": "microsoftInternal__NAV-999999__cf-5"}) + "\n")
        result = _next_cf_id("microsoftInternal__NAV-123456", cf_path)
        assert result == "microsoftInternal__NAV-123456__cf-1"

    def test_handles_gaps_in_numbering(self, tmp_path: Path):
        cf_path = tmp_path / "counterfactual.jsonl"
        cf_path.write_text(json.dumps({"instance_id": "microsoftInternal__NAV-123456__cf-1"}) + "\n" + json.dumps({"instance_id": "microsoftInternal__NAV-123456__cf-5"}) + "\n")
        result = _next_cf_id("microsoftInternal__NAV-123456", cf_path)
        assert result == "microsoftInternal__NAV-123456__cf-6"


class TestDetectFailToPass:
    def test_detects_test_procedure(self):
        result = _detect_fail_to_pass(SAMPLE_TEST_PATCH, "microsoftInternal__NAV-123456")
        assert len(result) == 1
        assert result[0].codeunitID == 148187
        assert "VerifyPurchDocEmissionsEnabled" in result[0].functionName

    def test_empty_patch_raises(self):
        empty_patch = """\
diff --git a/App/test/NoTests.Codeunit.al b/App/test/NoTests.Codeunit.al
index aaa..bbb 100644
--- a/App/test/NoTests.Codeunit.al
+++ b/App/test/NoTests.Codeunit.al
@@ -1,3 +1,4 @@ codeunit 99999 "NoTests"
 procedure Foo()
 begin
+    // just a comment
 end;
"""
        with pytest.raises(ValueError, match="No \\[Test\\] procedures found"):
            _detect_fail_to_pass(empty_patch, "microsoftInternal__NAV-123456")


class TestCreateCfEntry:
    @staticmethod
    def _write_base_dataset(tmp_path: Path, entry) -> Path:
        """Write a base dataset JSONL so create_cf_entry can resolve PASS_TO_PASS."""
        dataset_path = tmp_path / "bcbench.jsonl"
        import json as _json

        dataset_path.write_text(
            _json.dumps(entry.model_dump(by_alias=True, mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dataset_path

    def test_creates_entry_and_appends_to_jsonl(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        # Setup paths
        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        # Create base problem statement
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Base Problem\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        cf_entry = create_cf_entry(workspace, "Test variant description", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        assert cf_entry.instance_id.endswith("__cf-1")
        assert cf_entry.base_instance_id == entry.instance_id
        assert cf_entry.variant_description == "Test variant description"
        assert len(cf_entry.fail_to_pass) > 0

        # Verify appended to JSONL
        assert cf_path.exists()
        lines = cf_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["instance_id"] == cf_entry.instance_id

    def test_second_entry_gets_cf_2(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Base Problem\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        cf1 = create_cf_entry(workspace, "Variant 1", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)
        cf2 = create_cf_entry(workspace, "Variant 2", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        assert cf1.instance_id.endswith("__cf-1")
        assert cf2.instance_id.endswith("__cf-2")

    def test_with_fail_to_pass_override(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Base Problem\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        override = [TestEntry(codeunitID=99999, functionName=frozenset({"CustomTest"}))]
        cf_entry = create_cf_entry(workspace, "Override test", fail_to_pass_override=override, cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        assert cf_entry.fail_to_pass[0].codeunitID == 99999
        assert "CustomTest" in cf_entry.fail_to_pass[0].functionName

    def test_scaffolds_problem_statement_from_base(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Original Problem Statement\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        cf_entry = create_cf_entry(workspace, "Variant", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        # CF problem statement directory should exist with copied README
        cf_ps_dir = ps_dir / cf_entry.instance_id
        assert cf_ps_dir.exists()
        assert (cf_ps_dir / "README.md").read_text() == "# Original Problem Statement\n"

    def test_jsonl_key_ordering(self, tmp_path: Path):
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH)
        workspace = extract_workspace(entry, tmp_path / "ws")

        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Base Problem\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        create_cf_entry(workspace, "Variant", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        data = json.loads(cf_path.read_text().strip())
        expected_order = [
            "instance_id",
            "base_instance_id",
            "variant_description",
            "intervention_type",
            "problem_statement_override",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "test_patch",
            "patch",
        ]
        assert list(data.keys()) == expected_order

    def test_pass_to_pass_auto_populated_from_base(self, tmp_path: Path):
        base_p2p = [TestEntry(codeunitID=99999, functionName=frozenset({"ExistingPassTest"}))]
        entry = create_dataset_entry(patch=SAMPLE_FIX_PATCH, test_patch=SAMPLE_TEST_PATCH, pass_to_pass=base_p2p)
        workspace = extract_workspace(entry, tmp_path / "ws")

        cf_path = tmp_path / "counterfactual.jsonl"
        ps_dir = tmp_path / "problemstatement"
        ps_dir.mkdir()
        base_ps = ps_dir / entry.instance_id
        base_ps.mkdir()
        (base_ps / "README.md").write_text("# Base Problem\n")
        dataset_path = self._write_base_dataset(tmp_path, entry)

        cf_entry = create_cf_entry(workspace, "Variant", cf_path=cf_path, problem_statement_dir=ps_dir, dataset_path=dataset_path)

        assert len(cf_entry.pass_to_pass) == 1
        assert cf_entry.pass_to_pass[0].codeunitID == 99999
        assert "ExistingPassTest" in cf_entry.pass_to_pass[0].functionName
