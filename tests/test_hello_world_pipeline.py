"""Tests for the imaginary hello-world demo category."""

from bcbench.dataset import HelloWorldEntry
from bcbench.evaluate.hello_world import HelloWorldPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_evaluation_context, create_hello_world_entry


def _hello_world_context(tmp_path):
    entry = create_hello_world_entry()
    return create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.HELLO_WORLD)  # ty: ignore[invalid-argument-type]


def test_category_wires_hello_world_pieces():
    assert EvaluationCategory.HELLO_WORLD.entry_class is HelloWorldEntry
    assert isinstance(EvaluationCategory.HELLO_WORLD.pipeline, HelloWorldPipeline)
    assert EvaluationCategory.HELLO_WORLD.requires_container is False


def test_dataset_file_loads():
    entries = HelloWorldEntry.load(EvaluationCategory.HELLO_WORLD.dataset_path)
    assert entries
    assert all(isinstance(e.get_expected_output()["assertions"], list) for e in entries)


def test_setup_workspace_creates_git_repo(tmp_path):
    entry = create_hello_world_entry()
    repo_path = tmp_path / "repo"

    HelloWorldPipeline().setup_workspace(entry, repo_path)

    assert (repo_path / ".git").is_dir()
    assert (repo_path / "README.md").exists()


def test_empty_diff_persists_empty_output(tmp_path, monkeypatch):
    ctx = _hello_world_context(tmp_path)
    monkeypatch.setattr("bcbench.evaluate.hello_world.stage_and_get_diff", lambda _repo_path: (_ for _ in ()).throw(EmptyDiffError()))

    HelloWorldPipeline().evaluate(ctx)

    result = _read_only_result(ctx)
    assert result.output == ""
    assert result.error_message is None


def test_non_empty_diff_persists_raw_output(tmp_path, monkeypatch):
    ctx = _hello_world_context(tmp_path)
    monkeypatch.setattr("bcbench.evaluate.hello_world.stage_and_get_diff", lambda _repo_path: "diff --git a/Greeting.al b/Greeting.al\n+codeunit")

    HelloWorldPipeline().evaluate(ctx)

    result = _read_only_result(ctx)
    assert "codeunit" in result.output
    assert result.error_message is None


def _read_only_result(ctx) -> JudgeBasedEvaluationResult:
    from bcbench.config import get_config

    result_file = ctx.result_dir / f"{ctx.entry.instance_id}{get_config().file_patterns.result_pattern}"
    lines = result_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    return JudgeBasedEvaluationResult.model_validate_json(lines[0])
