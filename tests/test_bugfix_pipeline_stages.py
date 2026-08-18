from unittest.mock import patch

import pytest

from bcbench.evaluate.bugfix import _run_fix_check, _run_test_check
from bcbench.exceptions import BuildError, NoTestsExtractedError, TestExecutionError
from tests.conftest import create_evaluation_context

APP_PROJECTS = ["App\\Apps\\W1\\Shopify\\app"]
TEST_PATCH = "diff --git a/App/Apps/W1/Shopify/test/T.Codeunit.al b/App/Apps/W1/Shopify/test/T.Codeunit.al\n+    [Test]\n+    procedure T()\n"


@pytest.fixture
def context(tmp_path):
    ctx = create_evaluation_context(tmp_path)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return ctx


class TestRunTestCheck:
    def test_no_tests_extracted_yields_incorrect_outcome(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", side_effect=NoTestsExtractedError),
        ):
            outcome = _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert outcome.correct is False
        assert outcome.build is False
        assert "No tests extracted" in outcome.error_message

    def test_build_failure_yields_no_build(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", return_value=["t"]),
            patch("bcbench.evaluate.bugfix.run_red_green_check", side_effect=BuildError("App", "error AL0118: boom")),
        ):
            outcome = _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert outcome.build is False
        assert outcome.correct is False

    def test_test_passing_pre_patch_is_recorded(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", return_value=["t"]),
            patch("bcbench.evaluate.bugfix.run_red_green_check", side_effect=TestExecutionError("Fail")),
        ):
            outcome = _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert outcome.build is True
        assert outcome.pre_patch_failed is False
        assert outcome.post_patch_passed is False

    def test_test_failing_post_patch_is_recorded(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", return_value=["t"]),
            patch("bcbench.evaluate.bugfix.run_red_green_check", side_effect=TestExecutionError("Pass")),
        ):
            outcome = _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert outcome.build is True
        assert outcome.pre_patch_failed is True
        assert outcome.post_patch_passed is False

    def test_clean_red_green_is_correct(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", return_value=["t"]),
            patch("bcbench.evaluate.bugfix.run_red_green_check"),
        ):
            outcome = _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert outcome.correct is True

    def test_stage_a_rebuilds_every_project_to_undo_agent_publish(self, context):
        with (
            patch("bcbench.evaluate.bugfix.clean_project_paths"),
            patch("bcbench.evaluate.bugfix.extract_tests_from_patch", return_value=["t"]),
            patch("bcbench.evaluate.bugfix.run_red_green_check") as red_green,
        ):
            _run_test_check(context, TEST_PATCH, APP_PROJECTS)

        assert red_green.call_args.kwargs["initial_build_projects"] == context.entry.project_paths


class TestRunFixCheck:
    def test_clean_run_is_correct(self, context):
        with (
            patch("bcbench.evaluate.bugfix.setup_repo_prebuild"),
            patch("bcbench.evaluate.bugfix.set_runtime_version"),
            patch("bcbench.evaluate.bugfix.apply_patch"),
            patch("bcbench.evaluate.bugfix.build_and_publish_projects"),
            patch("bcbench.evaluate.bugfix.run_tests"),
        ):
            outcome = _run_fix_check(context, "diff --git a/a b/a\n+x\n")

        assert outcome.correct is True

    def test_gold_tests_failing_is_recorded(self, context):
        with (
            patch("bcbench.evaluate.bugfix.setup_repo_prebuild"),
            patch("bcbench.evaluate.bugfix.set_runtime_version"),
            patch("bcbench.evaluate.bugfix.apply_patch"),
            patch("bcbench.evaluate.bugfix.build_and_publish_projects"),
            patch("bcbench.evaluate.bugfix.run_tests", side_effect=TestExecutionError("Pass")),
        ):
            outcome = _run_fix_check(context, "diff --git a/a b/a\n+x\n")

        assert outcome.build is True
        assert outcome.passed is False

    def test_empty_app_patch_still_applies_gold_tests(self, context):
        with (
            patch("bcbench.evaluate.bugfix.setup_repo_prebuild"),
            patch("bcbench.evaluate.bugfix.set_runtime_version"),
            patch("bcbench.evaluate.bugfix.apply_patch") as apply_mock,
            patch("bcbench.evaluate.bugfix.build_and_publish_projects"),
            patch("bcbench.evaluate.bugfix.run_tests"),
        ):
            _run_fix_check(context, "")

        assert apply_mock.call_count == 1

    def test_runtime_version_is_reapplied_after_reset(self, context):
        with (
            patch("bcbench.evaluate.bugfix.setup_repo_prebuild") as prebuild,
            patch("bcbench.evaluate.bugfix.set_runtime_version") as runtime,
            patch("bcbench.evaluate.bugfix.apply_patch"),
            patch("bcbench.evaluate.bugfix.build_and_publish_projects"),
            patch("bcbench.evaluate.bugfix.run_tests"),
        ):
            _run_fix_check(context, "")

        assert prebuild.called
        assert runtime.called
