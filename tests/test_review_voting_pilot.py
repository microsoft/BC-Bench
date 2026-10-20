import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bcbench.dataset.codereview import CodeReviewEntry
from tools import review_voting_pilot as pilot
from tools.review_voting_evidence import aggregate, evidence_prompt, resolve_evidence, tree_digest, validate_votes


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("No real subprocess or paid calls in tests"))


def vote(verdict="supported", status="available"):
    return {
        "id": "F001",
        "verdict": verdict,
        "trigger": "the input branch is reached",
        "call_path_and_guards": "caller invokes helper; no earlier guard in the viewed branch",
        "impact": "operation fails on this input",
        "counterevidence": "the adjacent early exit is not taken",
        "source_view_status": status,
        "evidence": [
            {"tree": "source", "file": "helper.al", "line_start": 2, "line_end": 3, "quote": "begin\nend;"},
            {"tree": "knowledge", "file": "guide.md", "line_start": 2, "line_end": 2, "quote": "Check the guard."},
        ],
    }


def view_events(work, *, failed=False, masked=False, numbered=False):
    events = []
    for name, original, span in (
        ("source/helper.al", "begin\nend;", [2, 3]),
        ("knowledge/guide.md", "Check the guard.", [2, 2]),
    ):
        text = "****\nend;" if masked and name.startswith("source") else original
        if numbered:
            text = "\n".join(f"L{n}:{line}" for n, line in enumerate(text.splitlines(), span[0]))
        events.extend(
            [
                {"type": "tool.execution_start", "data": {"toolName": "view", "toolCallId": name, "arguments": {"path": str(work / name), "view_range": span}}},
                {"type": "tool.execution_complete", "data": {"toolCallId": name, "success": not failed, "result": {"content": text}}},
            ]
        )
    return events


def resolved(work, verdict="supported"):
    return resolve_evidence(validate_votes(["F001"], [vote(verdict)]), view_events(work), work)


@pytest.fixture
def safe_source(tmp_path):
    source, knowledge = tmp_path / "source", tmp_path / "knowledge"
    source.mkdir()
    knowledge.mkdir()
    (source / "helper.al").write_text("procedure Test()\nbegin\nend;\n")
    (knowledge / "guide.md").write_text("# Rule\nCheck the guard.\n")
    return source, knowledge


@pytest.mark.parametrize("numbered", [False, True])
def test_resolves_only_permitted_tool_view(tmp_path, numbered):
    votes = resolve_evidence(validate_votes(["F001"], [vote()]), view_events(tmp_path, numbered=numbered), tmp_path)
    assert votes[0].evidence_resolution == "tool_view_matched"
    assert votes[0].evidence[0].reference.line_start == 2
    assert votes[0].evidence[0].permitted_content
    assert votes[0].semantic_correctness == votes[0].disk_text_equivalence == "not_assessed"


@pytest.mark.parametrize("change", ["wrong-quote", "wrong-range", "unknown-file", "duplicate", "no-source", "no-knowledge"])
def test_incorrect_references_never_become_negative_votes(tmp_path, change):
    payload = vote("refuted")
    ref = payload["evidence"][0]
    if change == "wrong-quote":
        ref["quote"] = "invented"
    elif change == "wrong-range":
        ref.update(line_start=12, line_end=13)
    elif change == "unknown-file":
        ref["file"] = "missing.al"
    elif change == "duplicate":
        payload["evidence"].append(dict(ref))
    else:
        payload["evidence"] = [payload["evidence"][1 if change == "no-source" else 0]]
    votes = resolve_evidence(validate_votes(["F001"], [payload]), view_events(tmp_path), tmp_path)
    assert votes[0].evidence_resolution == "unresolved"
    with pytest.raises(ValueError, match="exclude"):
        aggregate(["F001"], [votes] * 3)


@pytest.mark.parametrize("status", ["unavailable", "redacted"])
def test_unavailable_source_is_explicit_even_with_empty_references(tmp_path, status):
    payload = vote("insufficient_evidence", status)
    payload["evidence"] = []
    votes = resolve_evidence(validate_votes(["F001"], [payload]), [], tmp_path)
    assert votes[0].evidence_resolution == status
    with pytest.raises(ValueError, match="exclude"):
        aggregate(["F001"], [votes] * 3)


def test_masked_view_not_matched_against_disk(safe_source, monkeypatch):
    source, _ = safe_source
    payload = vote()
    payload["evidence"][0]["quote"] = "****\nend;"
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("Cannot recover disk text"))
    votes = resolve_evidence(validate_votes(["F001"], [payload]), view_events(source.parent, masked=True), source.parent)
    assert votes[0].evidence_resolution == "redacted"


@pytest.mark.parametrize("kind", ["failure", "missing", "unbounded", "truncated", "wrong-number", "unsupported"])
def test_unsupported_views_fail_closed(tmp_path, kind):
    events = view_events(tmp_path, failed=kind == "failure")
    if kind == "missing":
        events = []
    elif kind == "unbounded":
        events[0]["data"]["arguments"].pop("view_range")
    elif kind == "truncated":
        events[1]["data"]["result"]["content"] = "truncated"
    elif kind == "wrong-number":
        events[1]["data"]["result"]["content"] = "L8:begin\nL9:end;"
    elif kind == "unsupported":
        events[1]["data"]["result"] = {"detailedContent": "begin\nend;"}
    result = resolve_evidence(validate_votes(["F001"], [vote()]), events, tmp_path)
    assert result[0].evidence_resolution == "unresolved"


@pytest.mark.parametrize("part", [0, 1])
def test_duplicate_tool_identity_rejected(tmp_path, part):
    events = view_events(tmp_path)
    events.append(events[part])
    with pytest.raises(ValueError, match="Duplicate"):
        resolve_evidence(validate_votes(["F001"], [vote()]), events, tmp_path)


@pytest.mark.parametrize("message", ["Access denied", "Content truncated", "Blocked by content exclusion"])
def test_error_shaped_view_is_unavailable_not_source_evidence(tmp_path, message):
    events = view_events(tmp_path)
    events[1]["data"]["result"]["content"] = message + "\nend;"
    payload = vote("refuted")
    payload["evidence"][0]["quote"] = message + "\nend;"
    result = resolve_evidence(validate_votes(["F001"], [payload]), events, tmp_path)
    assert result[0].evidence_resolution == "unavailable"
    with pytest.raises(ValueError, match="exclude"):
        aggregate(["F001"], [result] * 3)


@pytest.mark.parametrize("bad", [[], [vote(), vote()], [vote() | {"id": "F002"}], [vote() | {"unexpected": True}]])
def test_missing_duplicate_unknown_votes_rejected(bad):
    with pytest.raises(ValueError, match=r"Missing|validation"):
        validate_votes(["F001"], bad)


@pytest.mark.parametrize("path", ["../secret.al", "C:/secret.al", "/secret.al", "a\\secret.al"])
def test_reference_cannot_escape_tree(path):
    payload = vote()
    payload["evidence"][0]["file"] = path
    with pytest.raises(ValueError, match="tree-relative"):
        validate_votes(["F001"], [payload])


@pytest.mark.parametrize(
    ("verdicts", "b", "c"),
    [
        (["supported", "refuted", "refuted"], ["F001"], []),
        (["refuted", "supported", "supported"], [], ["F001"]),
        (["supported", "supported", "insufficient_evidence"], ["F001"], ["F001"]),
        (["insufficient_evidence"] * 3, [], []),
    ],
)
def test_preselected_first_voter_and_two_of_three(tmp_path, verdicts, b, c):
    assert aggregate(["F001"], [resolved(tmp_path, v) for v in verdicts]) == {"A": ["F001"], "B": b, "C": c}


def test_failed_voter_excludes_case_even_when_other_two_support(tmp_path):
    with pytest.raises(ValueError, match="failure is not a vote"):
        aggregate(["F001"], [resolved(tmp_path), None, resolved(tmp_path)])
    assert aggregate([], []) == {"A": [], "B": [], "C": []}


def test_changed_snapshot_detected(safe_source):
    source, _ = safe_source
    digest = tree_digest(source)
    (source / "helper.al").write_text("changed\n")
    with pytest.raises(ValueError, match="altered"):
        pilot.check_snapshot(source, digest)


def fake_cli(monkeypatch, *, failure_index=None, mutate=False):
    calls = []

    def process(args, **kwargs):
        assert "--prompt" in args
        work = kwargs["cwd"]
        calls.append(args)
        if len(calls) == failure_index:
            return SimpleNamespace(returncode=9)
        events = view_events(work)
        events.append({"type": "assistant.message", "data": {"phase": "final_answer", "content": json.dumps([vote()])}})
        kwargs["stdout"].write("\n".join(json.dumps(e) for e in events))
        kwargs["stdout"].flush()
        if mutate:
            (work / "source" / "helper.al").write_text("altered")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", process)
    monkeypatch.setenv("GH_TOKEN", "fixture-not-a-credential")
    return calls


def test_verifier_arguments_and_input_isolation(safe_source, monkeypatch, tmp_path):
    source, knowledge = safe_source
    calls = fake_cli(monkeypatch)
    candidates: list[pilot.Candidate] = [{"id": "F001", "comment": {"body": "fixture"}}]
    folder = tmp_path / "voter"
    result = pilot.run_verifier(folder, source, knowledge, {"changed_paths": ["helper.al"]}, candidates, "copilot.exe")
    assert result[0].evidence_resolution == "tool_view_matched"
    args = calls[0]
    assert "--model=gpt-5.6-sol" in args
    assert "--available-tools=view,rg,glob" in args
    assert "--disallow-temp-dir" in args
    assert "--add-dir" not in args
    assert "--allow-all-paths" not in args
    assert "fixture" not in args[-1]
    assert "begin" not in args[-1]
    assert json.loads((folder / "work" / "candidates.json").read_text()) == candidates
    assert {p.name for p in (folder / "work").iterdir()} == {"source", "knowledge", "context.json", "candidates.json"}
    with pytest.raises(FileExistsError):
        pilot.run_verifier(folder, source, knowledge, {}, candidates, "copilot.exe")
    assert len(calls) == 1


def test_mutated_verifier_inputs_preserve_failure(safe_source, monkeypatch, tmp_path):
    source, knowledge = safe_source
    calls = fake_cli(monkeypatch, mutate=True)
    with pytest.raises(ValueError, match="altered"):
        pilot.run_verifier(tmp_path / "voter", source, knowledge, {}, [{"id": "F001", "comment": {}}], "copilot.exe")
    assert len(calls) == 1
    assert (tmp_path / "voter" / "validation-failure.json").exists()


def test_empty_candidates_launch_no_process(safe_source, tmp_path):
    source, knowledge = safe_source
    assert pilot.run_verifier(tmp_path / "voter", source, knowledge, {}, [], "copilot.exe") == []
    assert not (tmp_path / "voter").exists()


def test_timeout_is_one_attempt_with_preserved_process_failure(safe_source, tmp_path, monkeypatch):
    source, knowledge = safe_source
    calls = []

    def timeout(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 1800)

    monkeypatch.setenv("GH_TOKEN", "fixture")
    monkeypatch.setattr(subprocess, "run", timeout)
    folder = tmp_path / "voter"
    with pytest.raises(subprocess.TimeoutExpired):
        pilot.run_verifier(folder, source, knowledge, {}, [{"id": "F001", "comment": {}}], "copilot.exe")
    assert len(calls) == 1
    assert json.loads((folder / "process.json").read_text())["status"] == "failed"


@pytest.fixture
def ready(tmp_path, monkeypatch):
    root, benchmark = tmp_path / "experiment", tmp_path / "benchmark"
    config = pilot.load_config()
    entries = [
        CodeReviewEntry.model_validate(
            {
                "instance_id": key,
                "repo": "microsoft/BCApps",
                "base_commit": "a" * 40,
                "created_at": "2026-01-01",
                "environment_setup_version": "27.0",
                "project_paths": [],
                "patch": "+++ b/helper.al",
                "metadata": {"area": "security"},
                "expected_comments": [{"file": "helper.al", "line_start": 2, "line_end": 3, "body": "fixture", "severity": "high"}] if n < 3 else [],
            }
        )
        for n, key in enumerate(config["cases"])
    ]
    monkeypatch.setattr(pilot, "selected_entries", lambda *a: entries)
    monkeypatch.setattr(pilot, "implementation_identity", lambda *a: {"fixture_identity": "frozen"})
    monkeypatch.setattr(pilot, "get_pr_review_version", lambda *a: config["engine_sha"])
    cli = {"path": str(tmp_path / "cli" / "copilot.exe"), "sha256": "0" * 64, "version": "1.0.88"}
    monkeypatch.setattr(pilot, "probe_cli", lambda *a: cli)
    monkeypatch.setattr(pilot, "command", lambda args, cwd=None: config["bcquality_sha"] if cwd == root / "knowledge" else "a" * 40)
    pilot.save(root / "selection.json", {"config": config, "fixture_identity": "frozen", "cli": cli})
    pilot.save(root / "engine" / "agents" / "ALReviewAgent" / "bcquality.config.yaml", {"bcquality": {"ref": config["bcquality_sha"]}})
    knowledge = root / "knowledge"
    (knowledge / "microsoft" / "knowledge").mkdir(parents=True)
    (knowledge / "microsoft" / "knowledge" / "rule.md").write_text("# Rule")
    (knowledge / "guide.md").write_text("# Rule\nCheck the guard.")
    for n in range(1, 7):
        source = root / "prepared" / f"case-{n:02}" / "source"
        source.mkdir(parents=True)
        (source / "helper.al").write_text("procedure Test()\nbegin\nend;\n")
    pilot.save(root / "inputs.json", {"source_sha256": [tree_digest(root / "prepared" / f"case-{n:02}" / "source") for n in range(1, 7)], "knowledge_sha256": tree_digest(knowledge)})
    return root, benchmark, entries, config


def test_offline_preflight_without_captures_or_credentials(ready, monkeypatch):
    root, benchmark, _, _ = ready
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    result = pilot.preflight(root, benchmark)
    assert result["status"] == "offline_checks_passed"
    assert result["paid_calls"] == 0
    assert not result["credentials_present"]
    assert result["limits"] == {"baseline": 6, "verifier": 18, "judge_batches": 6, "retries": 0}
    assert not (root / "protected-captures").exists()


def test_prepare_reuses_pipeline_and_finishes_with_offline_preflight(ready, monkeypatch, tmp_path):
    _, benchmark, entries, config = ready
    entries[0] = entries[0].model_copy(update={"base_commit": "b" * 40})
    destination = tmp_path / "new-preparation"
    seen = []

    def checkout(path, repository, commit):
        path.mkdir(parents=True)
        seen.append(("checkout", repository, commit))

    def command(args, cwd=None):
        assert "--prompt" not in args
        if "clone" in args:
            Path(args[-1]).mkdir()
        return ""

    def setup(self, entry, source):
        seen.append(("setup", entry.instance_id))
        (source / "helper.al").write_text("safe fixture")

    def knowledge(engine, pwsh, dest):
        dest.mkdir()
        (dest / "guide.md").write_text("safe knowledge")
        return dest

    def preflight(root, bench):
        assert len([item for item in seen if item[0] == "setup"]) == 6
        assert (root / "inputs.json").is_file()
        return {"paid_calls": 0}

    monkeypatch.setattr(pilot, "checkout_commit", checkout)
    monkeypatch.setattr(pilot, "command", command)
    monkeypatch.setattr(pilot.CodeReviewPipeline, "setup_workspace", setup)
    monkeypatch.setattr(pilot, "_prepare_bcquality_root", knowledge)
    monkeypatch.setattr(pilot, "preflight", preflight)
    pilot.prepare(destination, benchmark, tmp_path / "cli.exe")
    selection = json.loads((destination / "selection.json").read_text())
    assert selection["config"]["cases"] == [entry.instance_id for entry in entries]
    assert seen[0] == ("checkout", "https://github.com/microsoft/BC-ALAgents", config["engine_sha"])
    assert len([item for item in seen if item[0] == "checkout"]) == 3
    assert json.loads((destination / "preflight.json").read_text())["paid_calls"] == 0
    assert not (destination / "execution").exists()


@pytest.mark.parametrize("kind", ["sixth-source", "knowledge", "selection", "engine", "cli", "missing-inputs"])
def test_preflight_failure_launches_zero_paid_processes(ready, monkeypatch, kind):
    root, benchmark, _, _ = ready
    monkeypatch.setenv("GH_TOKEN", "fixture")
    monkeypatch.setattr(pilot, "run_pr_review_agent", lambda *a, **k: pytest.fail("Baseline must not start"))
    if kind == "sixth-source":
        (root / "prepared" / "case-06" / "source" / "helper.al").write_text("changed")
    elif kind == "knowledge":
        (root / "knowledge" / "guide.md").write_text("changed")
    elif kind == "selection":
        selection = json.loads((root / "selection.json").read_text())
        selection["config"]["cases"].pop()
        pilot.save(root / "selection.json", selection)
    elif kind == "engine":
        monkeypatch.setattr(pilot, "get_pr_review_version", lambda *a: "wrong")
    elif kind == "cli":
        monkeypatch.setattr(pilot, "probe_cli", lambda *a: {})
    else:
        (root / "inputs.json").unlink()
    with pytest.raises((ValueError, OSError)):
        pilot.run(root, benchmark)
    assert not (root / "execution").exists()


@pytest.mark.parametrize("empty_last", [True, False])
def test_entire_driver_with_failure_keeps_denominators_and_no_retries(ready, monkeypatch, empty_last):
    root, benchmark, entries, config = ready
    calls = fake_cli(monkeypatch, failure_index=10)
    order = []

    def baseline(entry, model, category, source, folder, **kwargs):
        assert model == config["root_model"]
        assert pilot.os.environ["COPILOT_REVIEW_LEAF_MODEL"] == config["leaf_model"]
        assert pilot.os.environ["COPILOT_REVIEW_CLI_VERSION"] == "1.0.88"
        assert not any(key.startswith("BCQUALITY_") for key in pilot.os.environ)
        order.append(entry.instance_id)
        comment = {"file": "helper.al", "line_start": 2, "line_end": 3, "body": "fixture", "severity": "high"}
        pilot.save(source / "review.json", [] if empty_last and entry is entries[-1] else [comment])
        return SimpleNamespace(model_dump=lambda **k: {"ai_credits": None}), None

    def judge(pairs, folder, model):
        assert len(order) == 6
        assert model == pilot.JUDGE
        return [True] * len(pairs)

    monkeypatch.setattr(pilot, "run_pr_review_agent", baseline)
    monkeypatch.setattr(pilot, "judge_verdicts", judge)
    monkeypatch.setenv("BCQUALITY_REF", "must-not-leak")
    original = dict(pilot.os.environ)
    pilot.run(root, benchmark)
    assert dict(pilot.os.environ) == original
    assert len(order) == 6
    assert len(calls) == (15 if empty_last else 18)
    report = json.loads((root / "results.json").read_text())
    assert report["denominators"] == {"selected": 6, "baseline_completed": 6, "baseline_scored": 6, "paired_scored": 5}
    assert len(report["exclusions"]) == 1
    assert report["exclusions"][0]["instance_id"] == entries[3].instance_id
    assert report["cases"][3]["arms"].keys() == {"A"}
    assert (root / "case-04" / "voter-3" / "decisions.json").is_file()
    assert (root / "case-05" / "voter-3" / "decisions.json").is_file()
    assert (root / "case-06" / "voter-1").exists() != empty_last
    assert report["summary"]["full_scored_baseline"]["cases"] == 6
    assert report["summary"]["complete_case_paired"]["A"]["cases"] == 5
    with pytest.raises(FileExistsError):
        pilot.run(root, benchmark)
    assert len(calls) == (15 if empty_last else 18)


def test_baseline_and_judge_failures_continue_other_independent_cases(ready, monkeypatch):
    root, benchmark, entries, _ = ready
    monkeypatch.setenv("GH_TOKEN", "fixture")
    baselines, judges = [], []

    def baseline(entry, model, category, source, folder, **kwargs):
        baselines.append(entry.instance_id)
        if entry is entries[0]:
            raise RuntimeError("fixture baseline failed")
        pilot.save(source / "review.json", [])
        return SimpleNamespace(model_dump=lambda **k: {}), None

    def score(entry, candidates, arms, folder):
        judges.append(entry.instance_id)
        if entry is entries[1]:
            raise RuntimeError("fixture judge failed")
        return {arm: {"generated": 0, "expected": 0, "matched": 0, "ignored": 0, "false": 0, "missed": 0, "matched_ids": [], "ignored_ids": []} for arm in arms}

    monkeypatch.setattr(pilot, "run_pr_review_agent", baseline)
    monkeypatch.setattr(pilot, "score_arms", score)
    pilot.run(root, benchmark)
    assert len(baselines) == 6
    assert len(judges) == 5
    report = json.loads((root / "results.json").read_text())
    assert report["denominators"] == {"selected": 6, "baseline_completed": 5, "baseline_scored": 4, "paired_scored": 4}
    assert [e["stage"] for e in report["exclusions"]] == ["baseline", "judge"]


@pytest.mark.parametrize("mode", ["--prepare", "--preflight", "--execute"])
def test_cli_dispatch_is_explicit(monkeypatch, tmp_path, mode):
    calls = []
    monkeypatch.setattr(pilot, "prepare", lambda *a: calls.append("prepare"))
    monkeypatch.setattr(pilot, "preflight", lambda *a: calls.append("preflight"))
    monkeypatch.setattr(pilot, "run", lambda *a: calls.append("execute"))
    args = [mode, "--root", str(tmp_path)]
    if mode == "--prepare":
        args += ["--cli", "copilot.exe"]
    pilot.main(args)
    assert calls == [mode[2:]]


def test_root_alone_never_starts_paid_execution(tmp_path):
    with pytest.raises(SystemExit):
        pilot.main(["--root", str(tmp_path)])


def test_cli_probe_is_non_inference_and_exact_version(monkeypatch, tmp_path):
    cli = tmp_path / "copilot.exe"
    cli.write_text("safe executable placeholder")
    seen = []

    def command(args):
        seen.append(args)
        assert "--prompt" not in args
        assert "-p" not in args
        return "GitHub Copilot CLI 1.0.88." if "--version" in args else "--available-tools --no-custom-instructions --disable-builtin-mcps --usage-output-file --disallow-temp-dir --no-remote-export"

    monkeypatch.setattr(pilot, "command", command)
    assert pilot.probe_cli(cli, pilot.load_config())["sha256"] == pilot.sha(cli)
    assert len(seen) == 2
    monkeypatch.setattr(pilot, "command", lambda *a: "GitHub Copilot CLI 1.0.99-2.")
    with pytest.raises(ValueError, match="Required engine-supported"):
        pilot.probe_cli(cli, pilot.load_config())


def test_prompt_preserves_evidence_requirements_and_no_raw_injection():
    prompt = evidence_prompt()
    for required in ("source AND knowledge", "counterevidence", "callers", "insufficient_evidence", "Never recover", "candidates.json"):
        assert required in prompt
    assert "Protected views:" not in prompt
    assert "Frozen diff:" not in prompt
