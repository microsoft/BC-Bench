from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from bcbench.evaluate.red_green import run_red_green_check
from bcbench.exceptions import TestExecutionError
from bcbench.types import ContainerConfig
from tests.conftest import create_dataset_entry, create_test_entry

INITIAL_BUILD_PROJECTS = ["App\\Initial"]
APP_PROJECTS = ["App\\Fixed"]
GOLD_PATCH = "diff --git a/gold.al b/gold.al\n+gold fix"
TEST_PATCH = "diff --git a/test.al b/test.al\n+generated test"


@pytest.fixture
def container() -> ContainerConfig:
    return ContainerConfig(name="test-container", username="test-user", password="test-password")


def _run(container: ContainerConfig) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    entry = create_dataset_entry(patch=GOLD_PATCH, test_patch=TEST_PATCH)
    generated_tests = [create_test_entry()]

    manager = MagicMock()
    with (
        patch("bcbench.evaluate.red_green.build_and_publish_projects") as build_and_publish_projects,
        patch("bcbench.evaluate.red_green.run_test_suite") as run_test_suite,
        patch("bcbench.evaluate.red_green.apply_patch") as apply_patch,
    ):
        manager.attach_mock(build_and_publish_projects, "build_and_publish_projects")
        manager.attach_mock(run_test_suite, "run_test_suite")
        manager.attach_mock(apply_patch, "apply_patch")

        run_red_green_check(
            repo_path=Path("/repo"),
            entry=entry,
            container=container,
            generated_tests=generated_tests,
            initial_build_projects=INITIAL_BUILD_PROJECTS,
            app_projects=APP_PROJECTS,
        )

    return manager, build_and_publish_projects, run_test_suite, apply_patch


def test_calls_happen_in_documented_order(container: ContainerConfig) -> None:
    manager, *_ = _run(container)

    assert [c[0] for c in manager.mock_calls] == [
        "build_and_publish_projects",
        "run_test_suite",
        "apply_patch",
        "build_and_publish_projects",
        "run_test_suite",
    ]


def test_red_before_green_expectations(container: ContainerConfig) -> None:
    _, _, run_test_suite, _ = _run(container)

    first_call, second_call = run_test_suite.call_args_list
    assert first_call.args[1] == "Fail"
    assert second_call.args[1] == "Pass"


def test_build_scopes_are_not_swapped(container: ContainerConfig) -> None:
    _, build_and_publish_projects, _, _ = _run(container)

    first_call, second_call = build_and_publish_projects.call_args_list
    assert first_call.args[1] == INITIAL_BUILD_PROJECTS
    assert second_call.args[1] == APP_PROJECTS


def test_apply_patch_receives_gold_patch_not_test_patch(container: ContainerConfig) -> None:
    _, _, _, apply_patch = _run(container)

    assert apply_patch.call_args.args[1] == GOLD_PATCH
    assert apply_patch.call_args.args[1] != TEST_PATCH


def test_positional_argument_order(container: ContainerConfig) -> None:
    entry = create_dataset_entry(patch=GOLD_PATCH, test_patch=TEST_PATCH)
    generated_tests = [create_test_entry()]

    with (
        patch("bcbench.evaluate.red_green.build_and_publish_projects") as build_and_publish_projects,
        patch("bcbench.evaluate.red_green.run_test_suite") as run_test_suite,
        patch("bcbench.evaluate.red_green.apply_patch"),
    ):
        run_red_green_check(
            repo_path=Path("/repo"),
            entry=entry,
            container=container,
            generated_tests=generated_tests,
            initial_build_projects=INITIAL_BUILD_PROJECTS,
            app_projects=APP_PROJECTS,
        )

    build_and_publish_projects.assert_has_calls(
        [
            call(Path("/repo"), INITIAL_BUILD_PROJECTS, container, entry.environment_setup_version),
            call(Path("/repo"), APP_PROJECTS, container, entry.environment_setup_version),
        ]
    )
    run_test_suite.assert_has_calls(
        [
            call(generated_tests, "Fail", container),
            call(generated_tests, "Pass", container),
        ]
    )


def test_red_failure_propagates_and_stops_the_pipeline(container: ContainerConfig) -> None:
    entry = create_dataset_entry(patch=GOLD_PATCH, test_patch=TEST_PATCH)
    generated_tests = [create_test_entry()]

    with (
        patch("bcbench.evaluate.red_green.build_and_publish_projects") as build_and_publish_projects,
        patch("bcbench.evaluate.red_green.run_test_suite", side_effect=TestExecutionError("Fail")) as run_test_suite,
        patch("bcbench.evaluate.red_green.apply_patch") as apply_patch,
        pytest.raises(TestExecutionError) as exc_info,
    ):
        run_red_green_check(
            repo_path=Path("/repo"),
            entry=entry,
            container=container,
            generated_tests=generated_tests,
            initial_build_projects=INITIAL_BUILD_PROJECTS,
            app_projects=APP_PROJECTS,
        )

    assert exc_info.value.expectation == "Fail"
    assert run_test_suite.call_count == 1
    apply_patch.assert_not_called()
    assert build_and_publish_projects.call_count == 1
