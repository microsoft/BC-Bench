"""Application-specific operations."""

from bcbench.operations.instruction_operations import copy_problem_statement_folder, setup_custom_agent, setup_instructions_from_config
from bcbench.operations.skills_operations import setup_agent_skills
from bcbench.operations.test_operations import extract_tests_from_patch

__all__ = [
    "copy_problem_statement_folder",
    "extract_tests_from_patch",
    "setup_agent_skills",
    "setup_custom_agent",
    "setup_instructions_from_config",
]
