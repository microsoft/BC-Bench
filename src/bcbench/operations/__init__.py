"""Operations for Business Central and Git."""

from bcbench.operations.bc_operations import (
    build_and_publish_projects,
    build_ps_app_build_and_publish,
    build_ps_dataset_tests_script,
    build_ps_test_script,
    copy_symbol_apps,
    ensure_package_cache,
    resolve_artifact_version_root,
    run_tests,
)
from bcbench.operations.filesystem_operations import remove_tree
from bcbench.operations.git_operations import (
    apply_patch,
    checkout_commit,
    clean_project_paths,
    clean_repo,
    clone_repo_at_revision,
    commit_changes,
    fetch_commit_if_missing,
    has_changes,
    init_repo,
    stage_and_get_diff,
)
from bcbench.operations.hooks_operations import setup_hooks
from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
from bcbench.operations.project_operations import categorize_projects
from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version, setup_repo_prebuild
from bcbench.operations.skills_operations import setup_agent_skills
from bcbench.operations.test_operations import extract_tests_from_patch

__all__ = [
    "apply_patch",
    "bootstrap_app_json",
    "build_and_publish_projects",
    "build_ps_app_build_and_publish",
    "build_ps_dataset_tests_script",
    "build_ps_test_script",
    "categorize_projects",
    "checkout_commit",
    "clean_project_paths",
    "clean_repo",
    "clone_repo_at_revision",
    "commit_changes",
    "copy_problem_statement_folder",
    "copy_symbol_apps",
    "ensure_package_cache",
    "extract_tests_from_patch",
    "fetch_commit_if_missing",
    "has_changes",
    "init_repo",
    "remove_tree",
    "resolve_artifact_version_root",
    "run_tests",
    "set_runtime_version",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_hooks",
    "setup_instructions_from_config",
    "setup_repo_prebuild",
    "stage_and_get_diff",
]
