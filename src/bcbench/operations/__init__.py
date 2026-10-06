"""Operations for Business Central and the BC-Bench workspace."""

from bcbench.operations.dataquery_operations import (
    execute_al_query,
    wrap_query_as_api,
)
from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version, setup_repo_prebuild
from bcbench.operations.skills_operations import setup_agent_skills
from bcbench.operations.test_operations import extract_tests_from_patch, run_tests

__all__ = [
    "bootstrap_app_json",
    "copy_problem_statement_folder",
    "execute_al_query",
    "extract_tests_from_patch",
    "run_tests",
    "set_runtime_version",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_instructions_from_config",
    "setup_repo_prebuild",
    "wrap_query_as_api",
]
