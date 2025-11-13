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
)
from bcbench.operations.instruction_operations import setup_instructions_from_config

__all__ = [
    "apply_patch",
    "build_and_publish_projects",
    "build_ps_app_build_and_publish",
    "build_ps_dataset_tests_script",
    "build_ps_test_script",
    "checkout_commit",
    "clean_repo",
    "run_tests",
    "setup_instructions_from_config",
]
