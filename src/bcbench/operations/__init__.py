"""Operations for Business Central and Git."""

from bcbench.operations.bc_operations import (
    build_and_publish_projects,
    build_ps_app_build_and_publish,
    build_ps_dataset_tests_script,
    build_ps_test_script,
    run_tests,
)
from bcbench.operations.git_operations import (
    apply_patch,
    checkout_commit,
    clean_repo,
    get_generated_diff,
)
from bcbench.operations.instruction_operations import setup_custom_agent, setup_instructions_from_config
from bcbench.operations.test_operations import extract_tests_from_patch

__all__ = [
    "apply_patch",
    "build_and_publish_projects",
    "build_ps_app_build_and_publish",
    "build_ps_dataset_tests_script",
    "build_ps_test_script",
    "checkout_commit",
    "clean_repo",
    "extract_tests_from_patch",
    "get_generated_diff",
    "run_tests",
    "setup_custom_agent",
    "setup_instructions_from_config",
]
