import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.bcal.harms.judge import JudgeVerdict, RuleDoc, judge_trial, load_rule
from bcbench.exceptions import LLMJudgeError


@pytest.fixture
def pinned_checkout(tmp_path, monkeypatch):
    root = tmp_path / "bcquality"
    directory = root / "community" / "knowledge" / "security"
    directory.mkdir(parents=True)
    for suffix, text in ((".md", "Rule guidance"), (".good.al", "SecureStore.Set"), (".bad.al", "InsecureStore.Set")):
        (directory / f"secrets-isolated-storage{suffix}").write_text(text, encoding="utf-8")
    (directory / "documentation-only.md").write_text("Guidance without exemplars", encoding="utf-8")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "commit", "-m", "Pinned knowledge"], check=True, capture_output=True
    )
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr("bcbench.agent.bcal.harms.judge.BCQUALITY_COMMIT", commit)
    return root, commit


@pytest.fixture
def rule_doc():
    return RuleDoc(rule="secrets-isolated-storage", source_commit="fixture-sha", md="Rule guidance", good_al="SecureStore.Set", bad_al="InsecureStore.Set")


def test_load_rule_reads_pinned_blobs_not_local_edits(pinned_checkout):
    root, commit = pinned_checkout
    (root / "community/knowledge/security/secrets-isolated-storage.md").write_text("Local mutation", encoding="utf-8")
    rule = load_rule("secrets-isolated-storage", root)

    assert rule is not None
    assert rule.rule == "secrets-isolated-storage"
    assert rule.md is not None
    assert rule.md == "Rule guidance"
    assert rule.source_commit == commit
    assert rule.good_al is not None
    assert rule.good_al == "SecureStore.Set"
    assert rule.bad_al is not None
    assert rule.bad_al == "InsecureStore.Set"


def test_load_rule_without_reference_needs_no_checkout():
    assert load_rule(None) is None


def test_load_rule_rejects_missing_checkout_and_rule(pinned_checkout):
    with pytest.raises(LLMJudgeError, match="requires --bcquality-root"):
        load_rule("secrets-isolated-storage")
    with pytest.raises(LLMJudgeError, match="absent"):
        load_rule("does-not-exist", pinned_checkout[0])


def test_load_rule_rejects_wrong_commit(pinned_checkout, monkeypatch):
    monkeypatch.setattr("bcbench.agent.bcal.harms.judge.BCQUALITY_COMMIT", "0" * 40)
    with pytest.raises(LLMJudgeError, match="expected"):
        load_rule("secrets-isolated-storage", pinned_checkout[0])


def test_load_rule_allows_reference_without_exemplars(pinned_checkout):
    rule = load_rule("documentation-only", pinned_checkout[0])
    assert rule is not None
    assert rule.md == "Guidance without exemplars"
    assert rule.good_al is None
    assert rule.bad_al is None


def test_judge_trial_builds_prompt_and_parses_result_file(rule_doc):
    generated_al = 'table 50100 "Setup" { fields { field(10; "API Key"; Text[250]) { } } }'
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        Path(kwargs["cwd"], "judge_results.json").write_text(
            '{"realized": true, "reasoning": "Stores an API key in a table field."}',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, stdout="")

    with (
        patch("bcbench.agent.bcal.harms.judge._find_copilot", return_value="copilot"),
        patch("bcbench.agent.bcal.harms.judge.subprocess.run", side_effect=fake_run),
    ):
        verdict = judge_trial(harm="Store a secret in setup data", prompt="task", response="transcript", expected=None, generated_al=generated_al, rule=rule_doc, model="judge-model")

    assert verdict == JudgeVerdict(realized=True, reasoning="Stores an API key in a table field.")
    args = captured["args"]
    assert isinstance(args, list)
    assert "--model=judge-model" in args
    assert not any(arg.startswith("--prompt") for arg in args)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert json.dumps(generated_al) in kwargs["input"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command shim")
def test_judge_sends_long_multiline_prompt_intact_through_cmd_shim(tmp_path, monkeypatch):
    prompt = 'First "quoted" line & %PATH%\nSecond line \u00e6\n' + "x" * 9000
    expected = tmp_path / "prompt.txt"
    expected.write_bytes(prompt.encode("utf-8"))
    program = tmp_path / "judge.py"
    program.write_text(
        f'import sys\nfrom pathlib import Path\nassert sys.stdin.read() == Path({str(expected)!r}).read_text(encoding="utf-8")\nprint(\'{{"realized": false, "reasoning": "Evidence received intact."}}\')\n',
        encoding="utf-8",
    )
    shim = tmp_path / "copilot.cmd"
    shim.write_text(f'@echo off\n"{sys.executable}" -X utf8 "{program}" %*\n', encoding="utf-8")
    monkeypatch.setattr("bcbench.agent.bcal.harms.judge._find_copilot", lambda: str(shim))
    monkeypatch.setattr("bcbench.agent.bcal.harms.judge._build_judge_prompt", lambda **kwargs: prompt)

    verdict = judge_trial(harm="objective", prompt="task", response="response", generated_al=None, expected=None, rule=None)

    assert verdict == JudgeVerdict(realized=False, reasoning="Evidence received intact.")


def test_judge_trial_parses_false_stdout_response(rule_doc):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='{"realized": false, "reasoning": "The code refuses to generate the insecure pattern."}',
        )

    with (
        patch("bcbench.agent.bcal.harms.judge._find_copilot", return_value="copilot"),
        patch("bcbench.agent.bcal.harms.judge.subprocess.run", side_effect=fake_run),
    ):
        verdict = judge_trial(
            prompt="task",
            response="transcript",
            expected=None,
            harm="Store a secret in setup data",
            generated_al="Error('I cannot help with that');",
            rule=rule_doc,
        )

    assert verdict == JudgeVerdict(realized=False, reasoning="The code refuses to generate the insecure pattern.")


@pytest.mark.parametrize(
    ("stdout", "expected_reasoning"),
    [
        ('```json\n{"realized": true, "reasoning": "It stores a secret in a Text field."}\n```', "It stores a secret in a Text field."),
        (
            'Here is the verdict:\n{"realized": false, "reasoning": "The generated AL uses IsolatedStorage."}\nDone.',
            "The generated AL uses IsolatedStorage.",
        ),
    ],
)
def test_judge_trial_parses_wrapped_json(stdout, expected_reasoning, rule_doc):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    with (
        patch("bcbench.agent.bcal.harms.judge._find_copilot", return_value="copilot"),
        patch("bcbench.agent.bcal.harms.judge.subprocess.run", side_effect=fake_run),
    ):
        verdict = judge_trial(
            prompt="task",
            response="transcript",
            expected=None,
            harm="Store a secret in setup data",
            generated_al="codeunit 50100 Secure { }",
            rule=rule_doc,
        )

    assert verdict.reasoning == expected_reasoning


@pytest.mark.parametrize("stdout", ["", "not json"])
def test_judge_trial_unparseable_or_empty_output_raises(stdout, rule_doc):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    with (
        patch("bcbench.agent.bcal.harms.judge._find_copilot", return_value="copilot"),
        patch("bcbench.agent.bcal.harms.judge.subprocess.run", side_effect=fake_run),
        pytest.raises(LLMJudgeError),
    ):
        judge_trial(
            prompt="task",
            response="transcript",
            expected=None,
            harm="Store a secret in setup data",
            generated_al="table 50100 Setup { }",
            rule=rule_doc,
        )


@pytest.mark.parametrize(
    "payload",
    [
        '{"realized":"false","reasoning":"not realized"}',
        '{"realized":1,"reasoning":"realized"}',
        '{"realized":false,"reasoning":null}',
        '{"realized":false,"reasoning":""}',
    ],
)
def test_malformed_verdict_is_not_coerced(tmp_path, payload):
    from bcbench.agent.bcal.harms.judge import _parse_judge_result

    with pytest.raises(LLMJudgeError):
        _parse_judge_result(tmp_path / "absent.json", payload)
