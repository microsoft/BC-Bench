import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench_core import bc, dataset, exceptions
from bcbench_core.bc import APP_UTILS_MODULE, BCBENCH_UTILS_MODULE
from bcbench_core.container import ContainerConfig


class TestEscapePsString:
    def test_escape_single_quote(self):
        assert bc.escape_ps_string("O'Brien") == "O''Brien"

    def test_escape_multiple_quotes(self):
        assert bc.escape_ps_string("It's a 'test'") == "It''s a ''test''"

    def test_no_escape_needed(self):
        assert bc.escape_ps_string("normal_string") == "normal_string"

    def test_empty_string(self):
        assert bc.escape_ps_string("") == ""

    def test_password_with_special_chars(self):
        assert bc.escape_ps_string("P@ss'word123") == "P@ss''word123"


class TestPowerShellScriptGeneration:
    def test_build_app_publish_script_basic(self):
        script = bc.build_ps_app_build_and_publish(
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
        script = bc.build_ps_app_build_and_publish(
            container_name="bc'server",
            username="admin",
            password="P@ss'word",
            project_path=Path("C:/NAV/App's/MyApp"),
            version="1.0.0.0",
        )

        assert "bc''server" in script
        assert "P@ss''word" in script
        assert "App''s" in script

    @pytest.mark.parametrize("function_names", [None, []])
    def test_build_test_script_without_functions(self, function_names):
        script = bc.build_ps_test_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            codeunit_id=50100,
            function_names=function_names,
        )

        assert "Import-Module BcContainerHelper" in script
        assert "bcserver" in script
        assert "50100" in script
        assert "Invoke-BCTest" in script
        # Should not have -functionNames parameter
        assert "-functionNames" not in script

    def test_build_test_script_with_functions(self):
        script = bc.build_ps_test_script(
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
        script = bc.build_ps_test_script(
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

    def test_build_dataset_tests_script(self):
        test_entries = '[{"codeunit": 50100, "function": "TestCreate"}]'

        script = bc.build_ps_dataset_tests_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            test_entries_json=test_entries,
            expectation="Pass",
        )

        assert "Import-Module BcContainerHelper" in script
        assert "bcserver" in script
        assert "Invoke-DatasetTests" in script
        assert "ConvertFrom-Json" in script
        assert "Pass" in script
        assert "$testEntries" in script

    def test_build_dataset_tests_script_with_quotes_in_json(self):
        # JSON with single quotes that need escaping
        test_entries = '[{"name": "Test\'s Function"}]'

        script = bc.build_ps_dataset_tests_script(
            container_name="bcserver",
            username="admin",
            password="Test123",
            test_entries_json=test_entries,
            expectation="Pass",
        )

        # Single quotes in JSON should be escaped
        assert "Test''s Function" in script

    def test_all_scripts_have_error_action_preference(self):
        scripts = [
            bc.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc.build_ps_test_script("bc", "admin", "pass", 50100),
            bc.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", "Pass"),
        ]

        for script in scripts:
            assert "$ErrorActionPreference = 'Stop'" in script

    def test_all_scripts_import_modules(self):
        scripts = [
            bc.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc.build_ps_test_script("bc", "admin", "pass", 50100),
            bc.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", "Pass"),
        ]

        for script in scripts:
            assert "Import-Module BcContainerHelper" in script
            assert f"Import-Module '{APP_UTILS_MODULE}'" in script

    def test_build_script_imports_bcbench_utils_for_update_app_project_version(self):
        script = bc.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0")

        assert f"Import-Module '{BCBENCH_UTILS_MODULE}'" in script
        assert BCBENCH_UTILS_MODULE.is_file()
        assert APP_UTILS_MODULE.is_file()

    def test_all_scripts_create_credential(self):
        scripts = [
            bc.build_ps_app_build_and_publish("bc", "admin", "pass", Path("/test"), "1.0"),
            bc.build_ps_test_script("bc", "admin", "pass", 50100),
            bc.build_ps_dataset_tests_script("bc", "admin", "pass", "[]", "Pass"),
        ]

        for script in scripts:
            assert "ConvertTo-SecureString" in script
            assert "System.Management.Automation.PSCredential" in script
            assert "-credential" in script.lower()

    def test_path_with_spaces(self):
        script = bc.build_ps_app_build_and_publish(
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
        script = bc.build_ps_app_build_and_publish(
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


class TestRunTestSuite:
    @pytest.fixture
    def mock_subprocess(self, monkeypatch):
        import subprocess

        calls = []

        def mock_run(*args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        return calls

    def test_test_entries_serialized_as_json(self, mock_subprocess):
        test_entries = [
            dataset.TestEntry(codeunitID=137404, functionName=frozenset({"ExchangeProductionBOMItemShouldSetEndingDate"})),
        ]

        bc.run_test_suite(
            test_entries=test_entries,
            expectation="Pass",
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
            dataset.TestEntry(codeunitID=100, functionName=frozenset({"TestB", "TestA"})),
            dataset.TestEntry(codeunitID=200, functionName=frozenset({"TestC"})),
        ]

        bc.run_test_suite(
            test_entries=test_entries,
            expectation="Pass",
            container=ContainerConfig(name="bcserver", username="admin", password="Test123", company="CRONUS"),
        )

        assert len(mock_subprocess) == 1
        command = mock_subprocess[0][0][0][-1]

        assert '"codeunitID":100' in command
        assert '"codeunitID":200' in command
        # Sorted, so the generated script is deterministic
        assert '"functionName":["TestA","TestB"]' in command
        assert "TestEntry(" not in command


_CONTAINER = ContainerConfig("bcserver", "admin", "secret", "CRONUS")


_OK = subprocess.CompletedProcess([], 0, stdout="", stderr="")


class TestBuildAndPublishProjects:
    def test_runs_build_script_per_project_in_repo(self, tmp_path):
        with patch.object(bc.subprocess, "run", return_value=_OK) as run:
            bc.build_and_publish_projects(tmp_path, ["App/MyApp"], _CONTAINER, "27.2")

        command = run.call_args.args[0]
        assert command[:4] == ["pwsh", "-NoProfile", "-NonInteractive", "-Command"]
        assert "Invoke-AppBuildAndPublish -containerName 'bcserver'" in command[-1]
        assert str(tmp_path / "App/MyApp") in command[-1]
        assert run.call_args.kwargs["cwd"] == tmp_path

    def test_baseapp_gets_its_own_timeout(self, tmp_path):
        with patch.object(bc.subprocess, "run", return_value=_OK) as run:
            bc.build_and_publish_projects(tmp_path, ["App/Layers/W1/BaseApp", "App/Layers/W1/Tests"], _CONTAINER, "27.2")
            bc.build_and_publish_projects(tmp_path, ["App/Layers/W1/BaseApp", "App/Layers/W1/Tests"], _CONTAINER, "27.2", timeout=10, baseapp_timeout=99)

        assert [c.kwargs["timeout"] for c in run.call_args_list] == [30 * 60, 5 * 60, 99, 10]

    def test_compile_failure_raises_build_error_with_compiler_errors(self, tmp_path):
        output = "noise\nsrc/Codeunit.al(3,1): error AL0118: The name 'Foo' does not exist\n"
        with patch.object(bc.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pwsh", output=output)), pytest.raises(exceptions.BuildError) as error:
            bc.build_and_publish_projects(tmp_path, ["App/MyApp"], _CONTAINER, "27.2")

        assert error.value.project_path == "App/MyApp"
        assert error.value.errors == "src/Codeunit.al(3,1): error AL0118: The name 'Foo' does not exist"

    def test_timeout_raises_build_timeout_expired(self, tmp_path):
        with patch.object(bc.subprocess, "run", side_effect=subprocess.TimeoutExpired("pwsh", 60)), pytest.raises(exceptions.BuildTimeoutExpired, match="App/MyApp after 60 seconds"):
            bc.build_and_publish_projects(tmp_path, ["App/MyApp"], _CONTAINER, "27.2", timeout=60)


_TESTS = [dataset.TestEntry(codeunitID=100, functionName=frozenset({"TestA"}))]


class TestRunTestSuiteOutcome:
    def test_defaults_to_three_minutes(self):
        with patch.object(bc.subprocess, "run", return_value=_OK) as run:
            bc.run_test_suite(_TESTS, "Pass", _CONTAINER)

        assert run.call_args.kwargs["timeout"] == 3 * 60

    def test_unmet_expectation_raises_test_execution_error(self):
        failure = subprocess.CalledProcessError(1, "pwsh", output="Tests failed for Codeunit 100\nTestA failed", stderr="boom")
        with patch.object(bc.subprocess, "run", side_effect=failure), pytest.raises(exceptions.TestExecutionError, match=r"expected: Pass") as error:
            bc.run_test_suite(_TESTS, "Pass", _CONTAINER)

        assert error.value.stderr == "boom"

    def test_timeout_raises_test_execution_timeout_expired(self):
        with patch.object(bc.subprocess, "run", side_effect=subprocess.TimeoutExpired("pwsh", 60)), pytest.raises(exceptions.TestExecutionTimeoutExpired, match="after 60 seconds") as error:
            bc.run_test_suite(_TESTS, "Fail", _CONTAINER, timeout=60)

        assert error.value.tests == '[{"codeunitID":100,"functionName":["TestA"]}]'

    def test_logs_test_output_at_debug(self, caplog):
        caplog.set_level("DEBUG", logger="bcbench_core.bc")
        with patch.object(bc.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="Tests passed for Codeunit 100", stderr="")):
            bc.run_test_suite(_TESTS, "Pass", _CONTAINER)

        assert "Test output:\nTests passed for Codeunit 100" in caplog.text
