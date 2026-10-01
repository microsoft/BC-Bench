"""Operations for Business Central and Git."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.operations.bc_operations import (
        build_and_publish_projects,
        build_ps_app_build_and_publish,
        build_ps_dataset_tests_script,
        build_ps_test_script,
        copy_symbol_apps,
        execute_al_query,
        resolve_artifact_version_root,
        run_tests,
        wrap_query_as_api,
    )
    from bcbench.operations.filesystem_operations import clear_directory, prepare_run_dir, remove_tree
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
    from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
    from bcbench.operations.project_operations import categorize_projects
    from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version, setup_repo_prebuild
    from bcbench.operations.skills_operations import setup_agent_skills
    from bcbench.operations.test_operations import extract_tests_from_patch

_EXPORTS = {
    "bc_operations": (
        "build_and_publish_projects",
        "build_ps_app_build_and_publish",
        "build_ps_dataset_tests_script",
        "build_ps_test_script",
        "copy_symbol_apps",
        "execute_al_query",
        "resolve_artifact_version_root",
        "run_tests",
        "wrap_query_as_api",
    ),
    "filesystem_operations": ("clear_directory", "prepare_run_dir", "remove_tree"),
    "git_operations": (
        "apply_patch",
        "checkout_commit",
        "clean_project_paths",
        "clean_repo",
        "clone_repo_at_revision",
        "commit_changes",
        "fetch_commit_if_missing",
        "has_changes",
        "init_repo",
        "stage_and_get_diff",
    ),
    "instruction_operations": ("copy_problem_statement_folder", "setup_custom_agent", "setup_instructions_from_config"),
    "project_operations": ("categorize_projects",),
    "setup_operations": ("bootstrap_app_json", "set_runtime_version", "setup_repo_prebuild"),
    "skills_operations": ("setup_agent_skills",),
    "test_operations": ("extract_tests_from_patch",),
}


def __getattr__(name: str) -> object:
    for module, names in _EXPORTS.items():
        if name in names:
            return getattr(import_module(f"bcbench.operations.{module}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "clear_directory",
    "clone_repo_at_revision",
    "commit_changes",
    "copy_problem_statement_folder",
    "copy_symbol_apps",
    "execute_al_query",
    "extract_tests_from_patch",
    "fetch_commit_if_missing",
    "has_changes",
    "init_repo",
    "prepare_run_dir",
    "remove_tree",
    "resolve_artifact_version_root",
    "run_tests",
    "set_runtime_version",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_instructions_from_config",
    "setup_repo_prebuild",
    "stage_and_get_diff",
    "wrap_query_as_api",
]
