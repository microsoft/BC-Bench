from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


def test_copilot_workflow_routes_code_review_through_copilot() -> None:
    workflow = _workflow("copilot-evaluation.yml")

    assert '"code-review"' in workflow
    assert "bcbench evaluate copilot" in workflow
    assert "bcbench evaluate pr-review" not in workflow
    assert "BC_PR_REVIEW_ROOT" not in workflow
    assert 'agent: "GitHub Copilot CLI"' in workflow


def test_claude_workflow_routes_code_review_through_claude() -> None:
    workflow = _workflow("claude-evaluation.yml")

    assert '"code-review"' in workflow
    assert "bcbench evaluate claude" in workflow
    assert 'agent: "Claude Code"' in workflow


def test_pr_review_workflow_is_fixed_to_code_review() -> None:
    workflow = _workflow("pr-review-evaluation.yml")

    assert "category: code-review" in workflow
    assert "bcbench evaluate pr-review" in workflow
    assert "repository: microsoft/BC-ALAgents" in workflow
    assert "copilot-requests: write" in workflow
    assert 'agent: "BC PR Review"' in workflow
    assert '"mai-code-1.1-flash"' in workflow
    assert "mai-code-1-flash-picker" not in workflow
    for input_name in ("model:", "test-run:", "repeat:", "git-ref:"):
        assert input_name in workflow
