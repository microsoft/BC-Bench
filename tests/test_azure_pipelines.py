import re
from pathlib import Path
from typing import Any

import yaml

from bcbench.types import EvaluationCategory

ROOT = Path(__file__).parents[1]
COPILOT_EVALUATION = ROOT / ".azuredevops" / "copilot-evaluation.yml"


def _copilot_evaluation() -> dict[str, Any]:
    pipeline = yaml.safe_load(COPILOT_EVALUATION.read_text(encoding="utf-8"))
    assert isinstance(pipeline, dict)
    return pipeline


def _jobs_template_parameters() -> dict[str, Any]:
    parameters = _copilot_evaluation()["extends"]["parameters"]["stages"][0]["jobs"][0]["parameters"]
    assert isinstance(parameters, dict)
    return parameters


def _categories_in(expression: object) -> set[str]:
    assert isinstance(expression, str)
    match = re.fullmatch(r"\$\{\{ in\(parameters\.category, (.+)\) \}\}", expression)
    assert match, expression
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_copilot_evaluation_offers_every_copilot_category() -> None:
    category = next(p for p in _copilot_evaluation()["parameters"] if p["name"] == "category")

    # NL2AL is evaluated with BCal in BC-Evals.
    assert set(category["values"]) == {c.value for c in EvaluationCategory} - {EvaluationCategory.NL2AL.value}


def test_copilot_evaluation_routes_categories_by_their_environment() -> None:
    parameters = _jobs_template_parameters()
    copilot_categories = [c for c in EvaluationCategory if c is not EvaluationCategory.NL2AL]

    assert _categories_in(parameters["container"]) == {c.value for c in copilot_categories if c.requires_container}
    assert _categories_in(parameters["skip_repo"]) == {c.value for c in copilot_categories if not c.requires_repo}


def test_copilot_evaluation_pins_the_same_copilot_cli_as_the_harness_action() -> None:
    action = (ROOT / ".github" / "actions" / "install-agent-harnesses" / "action.yml").read_text(encoding="utf-8")

    assert f"@github/copilot@{_jobs_template_parameters()['copilot_version']}" in action
