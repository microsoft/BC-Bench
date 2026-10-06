"""Operations for Business Central and the BC-Bench workspace."""

from bcbench.operations.bc_operations import (
    build_and_publish_projects,
    build_ps_app_build_and_publish,
    build_ps_dataset_tests_script,
    build_ps_test_script,
    copy_symbol_apps,
    resolve_artifact_version_root,
    run_tests,
)
from bcbench.operations.dataquery_operations import execute_al_query, wrap_query_as_api
from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version, setup_repo_prebuild
from bcbench.operations.skills_operations import setup_agent_skills
from bcbench.operations.test_operations import extract_tests_from_patch

__all__ = [
    "bootstrap_app_json",
    "build_and_publish_projects",
    "build_ps_app_build_and_publish",
    "build_ps_dataset_tests_script",
    "build_ps_test_script",
    "copy_problem_statement_folder",
    "copy_symbol_apps",
    "execute_al_query",
    "extract_tests_from_patch",
    "resolve_artifact_version_root",
    "run_tests",
    "set_runtime_version",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_instructions_from_config",
    "setup_repo_prebuild",
    "wrap_query_as_api",
]
