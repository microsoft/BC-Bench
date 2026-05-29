from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.types import EvaluationCategory

runner = CliRunner()


def test_bceval_config_prints_evaluators_and_core_score_to_stdout_when_no_github_output(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    result = runner.invoke(app, ["category", "bceval-config", "--category", "bug-fix"])

    assert result.exit_code == 0
    assert "evaluators=resolution_rate,build_rate" in result.stdout
    assert "core_score=ResolutionRate" in result.stdout


def test_bceval_config_appends_to_github_output_file_when_set(tmp_path, monkeypatch):
    output_file = tmp_path / "gh_output"
    output_file.write_text("pre_existing=keep\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    result = runner.invoke(app, ["category", "bceval-config", "--category", "test-generation"])

    assert result.exit_code == 0
    contents = output_file.read_text(encoding="utf-8")
    assert "pre_existing=keep" in contents
    assert "evaluators=resolution_rate,build_rate,pre_patch_failed_rate,post_patch_passed_rate" in contents
    assert "core_score=ResolutionRate" in contents


def test_bceval_config_supports_every_category(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    for category in EvaluationCategory:
        result = runner.invoke(app, ["category", "bceval-config", "--category", category.value])
        assert result.exit_code == 0, f"{category}: {result.stdout}"
        assert f"evaluators={','.join(category.evaluators)}" in result.stdout
        assert f"core_score={category.core_score}" in result.stdout


def test_list_prints_every_category_one_per_line():
    result = runner.invoke(app, ["category", "list"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines == [c.value for c in EvaluationCategory]
