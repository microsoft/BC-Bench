from collections.abc import Mapping

from bcbench.categories.base import PromptContext


def prompt_context(config: Mapping[str, object]) -> PromptContext:
    return {"is_gold_patch": False, "is_problem_statement": False}
