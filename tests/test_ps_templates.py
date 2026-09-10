from pathlib import Path
from unittest.mock import Mock

import pytest

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.operations import bc_operations
from bcbench.operations.test_execution import TestExpectation
from bcbench.types import ContainerConfig

_config = get_config()


class TestEscapePsString:
    def test_escape_single_quote(self):
        assert bc_operations._escape_ps_string("O'Brien") == "O''Brien"

    def test_escape_multiple_quotes(self):
        assert bc_operations._escape_ps_string("It's a 'test'") == "It''s a ''test''"

    def test_no_escape_needed(self):
        assert bc_operations._escape_ps_string("normal_string") == "normal_string"

    def test_empty_string(self):
        assert bc_operations._escape_ps_string("") == ""

    def test_password_with_special_chars(self):
        assert bc_operations._escape_ps_string("P@ss'word123") == "P@ss''word123"


class TestPowerShellScriptGeneration:
    def test_build_app_publish_script_basic(self):
        script = bc_operations.build_ps_app_build_and_publish(
            container_name="bcserver",
            username="admin",
            password="Test123",
            project_path=Path("C:/NAV/App/MyApp"),
            version="1.0.0.0",
        )

        assert "Import-Module BcContainerHelper -Force -DisableNameChecking" in script
        assert "$ErrorActionPreference = 'Stop'" in script
        assert "ConvertTo-SecureString 'Test123' -AsPlainText -Force" in script
        assert "New-Object System.Management.Automation.PSCredential('admin', $password)" in script
        assert "Update-AppProjectVersion -ProjectPath $projectPath -Version 1.0.0.0" in script

        # Ensure PowerShell variables use $ not $$
        assert "$ErrorActionPreference" in script
        assert "$projectPath" in script
        assert "$password" in script
        assert "$$password" not in script

    def test_build_app_publish_script_with_quotes(self):
        script = bc_operations.build_ps_app_build_and_publish(
            container_name="bc'server",
            username="admin",
            password="P@ss'word",
            project_path=Path("C:/NAV/App's/MyApp"),
            version="1.0.0.0",
        )

        assert "bc''server" in script
        assert "P@ss''word" in script
        assert "App''s" in script

    def test_build_test_script_without_functions(self):
        script = bc_operations.build_ps_test_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            codeunit_id=50100,
            function_names=None,
        )

        assert "Import-Module BcContainerHelper" in script
        assert "bcserver" in script
        assert "50100" in script
        assert "Invoke-BCTest" in script
        # Should not have -functionNames parameter
        assert "-functionNames" not in script

    def test_build_test_script_with_functions(self):
        script = bc_operations.build_ps_test_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            codeunit_id=50100,
            function_names=["TestCreate", "TestUpdate", "TestDelete"],
        )

        assert "Import-Module BcContainerHelper" in script
        assert "50100" in script
        assert "Invoke-BCTest" in script
        # Should have -functionNames parameter with array
        assert "-functionNames" in script
        assert "'TestCreate'" in script
        assert "'TestUpdate'" in script
        assert "'TestDelete'" in script

    def test_build_test_script_with_quoted_function_names(self):
        script = bc_operations.build_ps_test_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            codeunit_id=50100,
            function_names=["Test'Create", 'Test"Update'],
        )

        # Single quotes should be escaped
        assert "Test''Create" in script
        # Double quotes pass through (in PowerShell single-quoted strings)
        assert 'Test"Update' in script

    def test_build_test_script_accepts_shared_evidence_directory(self):
        script = bc_operations.build_ps_test_script(
            "bcserver",
            "admin",
            "pass",
            50100,
            ["TestCreate"],
            evidence_directory=Path(r"C:\repo with space\O'Brien"),
        )

        assert "$evidenceRoot = 'C:\\repo with space\\O''Brien'" in script

    def test_build_dataset_tests_script(self):
        test_entries = '[{"codeunit": 50100, "function": "TestCreate"}]'

        script = bc_operations.build_ps_dataset_tests_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            test_entries_json=test_entries,
            evidence_directory=Path(r"C:\repo\.bcbench-test-evidence"),
        )

        assert "Import-Module BcContainerHelper" in script
        assert "bcserver" in script
        assert "Invoke-DatasetTests" in script
        assert "ConvertFrom-Json" in script
        assert "-evidenceDirectory 'C:\\repo\\.bcbench-test-evidence'" in script
        assert "-expectation" not in script
        assert "$testEntries" in script

    def test_build_dataset_tests_script_quotes_json_and_evidence_path(self):
        # JSON with single quotes that need escaping
        test_entries = '[{"name": "Test\'s Function"}]'

        script = bc_operations.build_ps_dataset_tests_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            test_entries_json=test_entries,
            evidence_directory=Path(r"C:\repo with space\O'Brien\evidence"),
        )

        assert "Test''s Function" in script
        assert "-evidenceDirectory 'C:\\repo with space\\O''Brien\\evidence'" in script

    def test_all_scripts_have_error_action_preference(self):
        scripts = [
            bc_operations.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc_operations.build_ps_test_script("bc", "admin", "pass", 50100),
            bc_operations.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", Path("/evidence")),
        ]

        for script in scripts:
            assert "$ErrorActionPreference = 'Stop'" in script

    def test_all_scripts_import_modules(self):
        scripts = [
            bc_operations.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc_operations.build_ps_test_script("bc", "admin", "pass", 50100),
            bc_operations.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", Path("/evidence")),
        ]

        for script in scripts:
            assert "Import-Module BcContainerHelper" in script
            assert f"Import-Module '{_config.paths.ps_script_path / 'AppUtils.psm1'}'" in script  # AppUtils module

    def test_all_scripts_create_credential(self):
        scripts = [
            bc_operations.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc_operations.build_ps_test_script("bc", "admin", "pass", 50100),
            bc_operations.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", Path("/evidence")),
        ]

        for script in scripts:
            assert "ConvertTo-SecureString" in script
            assert "System.Management.Automation.PSCredential" in script
            assert "-credential" in script.lower()

    def test_path_with_spaces(self):
        script = bc_operations.build_ps_app_build_and_publish(
            container_name="bcserver",
            username="admin",
            password="Test123",
            project_path=Path("C:/Program Files/NAV/App"),
            version="1.0.0.0",
        )

        # Path will be in Windows format with spaces preserved
        assert "Program Files" in script
        assert "NAV" in script
        assert "App" in script

    def test_version_is_not_quoted(self):
        script = bc_operations.build_ps_app_build_and_publish(
            container_name="bcserver",
            username="admin",
            password="Test123",
            project_path=Path("C:/NAV/App"),
            version="27.0",
        )

        # Version should appear without quotes in the script
        assert "Version 27.0" in script or "-Version 27.0" in script
        # Should not have quotes around version
        assert "'27.0'" not in script
        assert '"27.0"' not in script


def test_app_utils_runs_each_requested_function_and_appends_junit():
    app_utils = (_config.paths.ps_script_path / "AppUtils.psm1").read_text(encoding="utf-8")

    assert "foreach ($functionName in $functionsToRun)" in app_utils
    assert "testFunction            = $functionName" in app_utils
    assert "AppendToJUnitResultFile = $appendToResult" in app_utils
    assert "$functionNames -join '|'" not in app_utils


def test_verify_build_and_tests_uses_evidence_validation():
    verification_script = (_config.paths.ps_script_path / "Verify-BuildAndTests.ps1").read_text(encoding="utf-8")

    assert "Invoke-DatasetTestsWithExpectation" in verification_script
    assert "load_test_run_summary" in verification_script
    assert "-evidenceDirectory $evidenceDirectory" in verification_script
    assert "Invoke-DatasetTests -containerName" not in verification_script
    assert "uv run --project $bcBenchRoot python" in verification_script


class TestRunTestSuite:
    @pytest.fixture
    def mock_subprocess(self, monkeypatch):
        import subprocess

        calls = []

        def mock_run(*args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(bc_operations, "load_test_run_summary", lambda *_args: Mock(require=lambda _expectation: None), raising=False)
        return calls

    def test_test_entries_serialized_as_json(self, mock_subprocess):
        test_entries = [
            TestEntry(codeunitID=137404, functionName=frozenset({"ExchangeProductionBOMItemShouldSetEndingDate"})),
        ]

        bc_operations.run_test_suite(
            repo_path=Path.cwd(),
            test_entries=test_entries,
            expectation=TestExpectation.ALL_PASS,
            container=ContainerConfig(name="bcserver", username="admin", password="Test123", company="CRONUS"),
        )

        assert len(mock_subprocess) == 1
        command = mock_subprocess[0][0][0][-1]  # Get the PowerShell command string

        # Should contain valid JSON format, not Python repr
        assert '"codeunitID":137404' in command
        assert '"functionName":["ExchangeProductionBOMItemShouldSetEndingDate"]' in command
        # Should NOT contain Python repr format
        assert "TestEntry(" not in command

    def test_multiple_test_entries_serialized_as_json(self, mock_subprocess):
        test_entries = [
            TestEntry(codeunitID=100, functionName=frozenset({"TestA", "TestB"})),
            TestEntry(codeunitID=200, functionName=frozenset({"TestC"})),
        ]

        bc_operations.run_test_suite(
            repo_path=Path.cwd(),
            test_entries=test_entries,
            expectation=TestExpectation.ALL_PASS,
            container=ContainerConfig(name="bcserver", username="admin", password="Test123", company="CRONUS"),
        )

        assert len(mock_subprocess) == 1
        command = mock_subprocess[0][0][0][-1]

        assert '"codeunitID":100' in command
        assert '"codeunitID":200' in command
        assert '"functionName":' in command
        assert "TestEntry(" not in command
