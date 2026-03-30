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
    clean_project_paths,
    clean_repo,
    commit_changes,
    stage_and_get_diff,
)
from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
from bcbench.operations.project_operations import categorize_projects
from bcbench.operations.setup_operations import setup_repo_postbuild, setup_repo_prebuild
from bcbench.operations.skills_operations import setup_agent_skills
from bcbench.operations.test_operations import extract_tests_from_patch

__all__ = [
    "apply_patch",
    "build_and_publish_projects",
    "build_ps_app_build_and_publish",
    "build_ps_dataset_tests_script",
    "build_ps_test_script",
    "categorize_projects",
    "checkout_commit",
    "clean_project_paths",
    "clean_repo",
    "commit_changes",
    "copy_problem_statement_folder",
    "extract_tests_from_patch",
    "run_tests",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_instructions_from_config",
    "setup_repo_postbuild",
    "setup_repo_prebuild",
    "stage_and_get_diff",
]
