import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bcbench.agent.copilot.isolated_review import _quarantine_project_agents, isolated_environment, run_isolated_review
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import AgentConfig, AgentMetrics
from tests.conftest import create_codereview_entry

ROOT = Path(__file__).parents[1]


def test_isolated_env_drops_external_customization_and_preserves_only_allowed_auth(tmp_path, monkeypatch):
    for key in ("COPILOT_HOME", "COPILOT_CUSTOM_INSTRUCTIONS_DIRS", "BCQUALITY_ROOT", "BASH_ENV", "NODE_OPTIONS", "COPILOT_PROVIDER_BASE_URL", "AGENT_SECRET"):
        monkeypatch.setenv(key, "must-not-leak")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "auth-only")
    env = isolated_environment(tmp_path)
    assert env["COPILOT_GITHUB_TOKEN"] == "auth-only"
    assert "must-not-leak" not in env.values()
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path)
    assert env["COPILOT_HOME"] == str(tmp_path / ".copilot")
    assert env["COPILOT_AUTO_UPDATE"] == "false"


@pytest.mark.parametrize("failure", [None, "version", "plugin", "skill", "review", "timeout"])
def test_isolated_review_lifecycle_and_bounded_evidence(tmp_path, failure):
    repo, out = tmp_path / "repo", tmp_path / "out"
    repo.mkdir()
    config = AgentConfig.from_file(ROOT / "src" / "bcbench" / "agent" / "shared" / "config.yaml")
    disabled = False
    homes = []

    def cli(_cli, _repo, env, *args):
        nonlocal disabled
        homes.append(Path(env["HOME"]))
        assert Path(env["COPILOT_HOME"]).is_dir()
        if args == ("--version",):
            return "GitHub Copilot CLI 1.0.99." if failure == "version" else "GitHub Copilot CLI 1.0.88.\n"
        if args[:2] == ("skill", "disable"):
            disabled = True
            return ""
        if args == ("skill", "list", "--json"):
            return json.dumps([{"name": "fixture-skill", "source": "project", "enabled": not disabled or failure == "skill", "description": "RAW PROMPT", "path": "PRIVATE PATH"}])
        if args == ("plugin", "list", "--json"):
            return '[{"name":"forbidden"}]' if failure == "plugin" else "[]"
        if args == ("instruction", "list", "--json"):
            return "[]"
        raise AssertionError(args)

    def invoke(**kwargs):
        assert kwargs["log_transcript"] is False
        assert "--log-level=none" in kwargs["extra_args"]
        assert "--excluded-tools=skill,task" in kwargs["extra_args"]
        assert kwargs["custom_instructions"] is False
        assert "Report only Medium, High or Critical" in kwargs["prompt"]
        if failure == "review":
            raise subprocess.CalledProcessError(1, "secret command", output="TOKEN RAW", stderr="TOKEN RAW")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("secret command", 1, output="TOKEN RAW")
        return AgentMetrics(execution_time=1, turn_count=2), ""

    with (
        patch("bcbench.agent.copilot.isolated_review._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.isolated_review._cli", side_effect=cli),
        patch("bcbench.agent.copilot.isolated_review.invoke_copilot", side_effect=invoke) as model,
    ):
        if failure:
            with pytest.raises((AgentError, AgentTimeoutError)) as caught:
                run_isolated_review(create_codereview_entry(), "gpt-5.6-sol", repo, out, config)
            assert "TOKEN RAW" not in str(caught.value)
        else:
            metrics, experiment = run_isolated_review(create_codereview_entry(), "gpt-5.6-sol", repo, out, config)
            assert metrics is not None
            assert metrics.turn_count == 2
            assert experiment.review_integration == "none"
        assert model.call_count == int(failure in (None, "review", "timeout"))
    text = (out / "_plain-review-evidence.json").read_text()
    evidence = json.loads(text)
    assert evidence["status"] == ("completed" if failure is None else "timeout" if failure == "timeout" else "failed")
    assert "TOKEN RAW" not in text
    assert "RAW PROMPT" not in text
    assert "PRIVATE PATH" not in text
    assert all(not home.exists() for home in homes)
    if failure is None:
        assert evidence["before"] == evidence["after"]
        assert evidence["before"]["plugins"] == []
        assert evidence["before"]["skills"][0]["enabled"] is False


def test_project_configuration_is_not_deleted_or_silently_ignored(tmp_path):
    repo = tmp_path / "repo"
    path = repo / ".github" / "agents"
    path.mkdir(parents=True)
    config = AgentConfig.from_file(ROOT / "src" / "bcbench" / "agent" / "shared" / "config.yaml")
    with patch("bcbench.agent.copilot.isolated_review._find_copilot", return_value="copilot"), patch("bcbench.agent.copilot.isolated_review.invoke_copilot") as model:
        with pytest.raises(AgentError, match="preflight"):
            run_isolated_review(create_codereview_entry(), "gpt-5.6-sol", repo, tmp_path / "out", config)
        model.assert_not_called()
    assert path.is_dir()


@pytest.fixture
def disposable_repo(tmp_path, monkeypatch):
    repo = tmp_path / "testbed"
    agents = repo / ".github" / "agents"
    agents.mkdir(parents=True)
    (agents / "sample.agent.md").write_bytes(b"---\nname: Sample\n---\nOriginal configuration\n")
    (repo / "source.al").write_text("original\n", encoding="utf-8")

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    (repo / "source.al").write_text("reviewed\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    return repo, git


@pytest.mark.parametrize("failure", [False, True])
def test_agent_configuration_quarantine_preserves_real_git_diff_and_restores(disposable_repo, failure):
    repo, git = disposable_repo
    agent = repo / ".github" / "agents" / "sample.agent.md"
    original = agent.read_bytes()
    before = git("diff", "HEAD")
    index = git("ls-files", "-v")
    evidence = {}

    def run():
        with _quarantine_project_agents(repo, evidence):
            assert not agent.parent.exists()
            assert git("diff", "HEAD") == before
            assert git("diff", "--cached") == b""
            assert b".github/agents" not in git("status", "--porcelain")
            if failure:
                raise RuntimeError("reviewer failed")

    if failure:
        with pytest.raises(RuntimeError, match="reviewer failed"):
            run()
    else:
        run()
    assert agent.read_bytes() == original
    assert git("diff", "HEAD") == before
    assert git("ls-files", "-v") == index
    assert not list(repo.parent.glob("bcbench-agent-config-*"))
    record = evidence["quarantined_project_agents"]
    assert record["restored"] is True
    assert record["diff_before_sha256"] == record["diff_isolated_sha256"] == record["diff_after_sha256"]


def test_quarantine_rejects_modified_configuration_without_suppressing_it(disposable_repo):
    repo, git = disposable_repo
    agent = repo / ".github" / "agents" / "sample.agent.md"
    agent.write_text("legitimate configuration change\n")
    before = git("diff", "HEAD")
    with pytest.raises(AgentError, match="modified or untracked"), _quarantine_project_agents(repo, {}):
        pytest.fail("must not run")
    assert git("diff", "HEAD") == before
    assert agent.read_text() == "legitimate configuration change\n"


def test_quarantine_detects_source_contamination_and_restores_configuration(disposable_repo):
    repo, _ = disposable_repo
    evidence = {}
    with pytest.raises(AgentError, match="contaminated output"), _quarantine_project_agents(repo, evidence):
        (repo / "source.al").write_text("unexpected reviewer modification\n")
    assert (repo / ".github" / "agents" / "sample.agent.md").is_file()
    assert evidence["quarantined_project_agents"]["restored"] is True
    assert (repo / "source.al").read_text() == "unexpected reviewer modification\n"


def test_final_cli_prompt_and_tool_diff_see_only_original_fixture_changes(disposable_repo, tmp_path):
    repo, git = disposable_repo
    before = git("diff", "HEAD")
    config = AgentConfig.from_file(ROOT / "src" / "bcbench" / "agent" / "shared" / "config.yaml")

    def cli(_cli, _repo, env, *args):
        return "GitHub Copilot CLI 1.0.88.\n" if args == ("--version",) else "[]"

    def subprocess_run(command, **kwargs):
        prompt = next(arg.removeprefix("--prompt=") for arg in command if arg.startswith("--prompt="))
        assert "git diff HEAD" in prompt
        assert ".github/agents" not in prompt
        assert git("diff", "HEAD") == before
        assert subprocess.run(["git", "diff", "HEAD"], cwd=repo, env=kwargs["env"], capture_output=True, check=True).stdout == before
        assert not (repo / ".github" / "agents").exists()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    # Mock only model execution; real git exercises the same diff a tool call reads.
    real_run = subprocess.run

    def route(command, **kwargs):
        return real_run(command, **kwargs) if command[0] == "git" else subprocess_run(command, **kwargs)

    with (
        patch("bcbench.agent.copilot.isolated_review._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.isolated_review._cli", side_effect=cli),
        patch("subprocess.run", side_effect=route),
    ):
        run_isolated_review(create_codereview_entry(), "gpt-5.6-sol", repo, tmp_path / "out", config)
    assert git("diff", "HEAD") == before
    evidence = json.loads((tmp_path / "out" / "_plain-review-evidence.json").read_text())
    assert evidence["status"] == "completed"
    assert evidence["quarantined_project_agents"]["restored"] is True


def test_plain_workflow_never_publishes_or_requeues_and_uploads_only_evidence_file():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "pr-review-evaluation.yml").read_text())
    jobs = workflow["jobs"]
    assert "inputs.review-integration == 'none'" in jobs["summarize-results"]["with"]["mock"]
    assert "inputs.review-integration != 'none'" in jobs["requeue"]["if"]
    steps = jobs["evaluate-with-pr-review"]["steps"]
    run = next(step for step in steps if step.get("id") == "evaluate-plain")
    assert run["if"] == "inputs.review-integration == 'none'"
    assert "--category code-review --isolated-review" in run["run"]
    assert "repeat=1 only" in run["run"]
    assert run["env"]["COPILOT_AUTO_UPDATE"] == "false"
    upload = next(step for step in steps if step["name"] == "Upload isolated plain review evidence")
    assert upload["if"] == "always() && inputs.review-integration == 'none'"
    assert upload["with"]["path"].endswith("/_plain-review-evidence.json")
    assert "*" not in upload["with"]["path"]
    assert upload["with"]["if-no-files-found"] == "error"
