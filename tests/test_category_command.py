from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.types import EvaluationCategory

runner = CliRunner()


def test_bceval_config_writes_nothing_to_stdout_when_no_github_output(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    result = runner.invoke(app, ["category", "bceval-config", "--category", "bug-fix"])

    assert result.exit_code == 0
    assert "evaluators=" not in result.stdout
    assert "core_score=" not in result.stdout


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


def test_bceval_config_supports_every_category(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    for category in EvaluationCategory:
        output_file = tmp_path / f"gh_output_{category.value}"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        result = runner.invoke(app, ["category", "bceval-config", "--category", category.value])
        assert result.exit_code == 0, f"{category}: {result.stdout}"

        contents = output_file.read_text(encoding="utf-8")
        assert f"evaluators={','.join(category.evaluators)}" in contents
        assert f"core_score={category.core_score}" in contents


def test_list_prints_every_category_one_per_line():
    result = runner.invoke(app, ["category", "list"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines == [c.value for c in EvaluationCategory]


def test_runtime_config_supports_every_category(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    for category in EvaluationCategory:
        output_file = tmp_path / f"gh_output_{category.value}"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        result = runner.invoke(app, ["category", "runtime-config", "--category", category.value])
        assert result.exit_code == 0, f"{category}: {result.stdout}"

        contents = output_file.read_text(encoding="utf-8")
        assert f"runner={category.runner}" in contents
        assert f"requires-container={str(category.requires_container).lower()}" in contents


def test_runtime_config_marks_code_review_as_containerless_on_hosted_runner(tmp_path, monkeypatch):
    output_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    result = runner.invoke(app, ["category", "runtime-config", "--category", "code-review"])

    assert result.exit_code == 0
    contents = output_file.read_text(encoding="utf-8")
    assert "requires-container=false" in contents
    assert "runner=windows-latest" in contents
