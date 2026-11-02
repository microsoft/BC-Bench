import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate import review_voting as voting
from bcbench.evaluate.review_verification import ResolvedDecision


@pytest.fixture(autouse=True)
def no_inference(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("No real processes in voting tests"))


@pytest.fixture
def entry():
    return CodeReviewEntry(
        instance_id="synthetic__fixture-01",
        repo="microsoft/BCApps",
        base_commit="a" * 40,
        created_at="2026-01-01",
        environment_setup_version="27.0",
        project_paths=[],
        patch="+++ b/example.al\n",
        expected_comments=[{"file": "example.al", "line_start": 1, "body": "required", "severity": "high"}],
    )


def resolved(verdict="supported", validity="tool_view_matched"):
    return ResolvedDecision.model_validate_json(
        json.dumps(
            {
                "decision": {
                    "id": "F001",
                    "verdict": verdict,
                    "trigger": "fixture",
                    "impact": "fixture",
                    "counterevidence": "fixture",
                    "call_path_and_guards": "fixture",
                    "source_view_status": "available",
                    "evidence": [],
                },
                "evidence_resolution": validity,
                "reason": "test fixture",
                "evidence": [],
            }
        )
    )


@pytest.fixture
def baseline_fixture(tmp_path, monkeypatch, entry):
    source = tmp_path / "source"
    source.mkdir()
    (source / "example.al").write_text("unchanged")
    monkeypatch.setattr(voting.CodeReviewPipeline, "setup_workspace", lambda *a: None)
    monkeypatch.setattr(voting, "validate_baseline", lambda *a: None)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(voting.tempfile, "mkdtemp", lambda **k: str(runtime))

    def baseline(folder):
        (folder / "bcquality").mkdir(parents=True)
        voting.save(source / "review.json", [entry.expected_comments[0].model_dump(mode="json")])
        voting.save(folder / "metrics.json", {"ai_credits": 1, "total_tokens": 10})

    return source, baseline


def test_exact_population_and_separate_phase_budgets():
    dataset = Path("dataset/codereview.jsonl")
    smoke, full = voting.plan(dataset, "smoke"), voting.plan(dataset, "full")
    assert smoke["selected"] == list(voting.SMOKE)
    assert smoke["budgets"] == {"reviews": 2, "verifiers": 6, "judge_batches": 2}
    assert len(full["selected"]) == 145
    assert full["budgets"] == {"reviews": 145, "verifiers": 435, "judge_batches": 106}
    assert full["config"]["retries"] == 0
    assert full["config"]["publish"] is False


def test_changed_dataset_fails_before_calls(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Dataset differs"):
        voting.plan(path, "full")


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [{"pair": 1, "match": True}],
        [{"pair": 1, "match": True}, {"pair": 1, "match": False}],
        [{"pair": 1, "match": "false"}, {"pair": 2, "match": False}],
        [{"pair": True, "match": True}, {"pair": 2, "match": False}],
        [{"pair": 1, "match": True}, {"pair": 3, "match": False}],
    ],
)
def test_judge_missing_duplicate_wrong_type_and_unknown_fail(raw):
    with pytest.raises(ValueError, match="Judge"):
        voting.strict_judge_verdicts(json.dumps(raw), 2)


def test_judge_false_is_explicit_not_missing_default():
    assert voting.strict_judge_verdicts('[{"pair":2,"match":false},{"pair":1,"match":true}]', 2) == [True, False]


def test_full_edge_graph_reassigns_match_for_subset(entry):
    first = entry.expected_comments[0].model_dump(mode="json")
    second = first | {"line_start": 20}
    candidates = [{"id": "F001", "comment": first}, {"id": "F002", "comment": second}]
    scores = voting.score_subsets(entry, candidates, {"A": ["F001", "F002"], "B": ["F002"], "C": []}, [True, True])
    assert scores["A"]["tp"] == scores["B"]["tp"] == 1
    assert scores["B"]["matched_ids"] == ["F002"]
    assert scores["C"]["fn"] == 1


def test_identical_candidate_values_cannot_share_a_judge_verdict(entry):
    comment = entry.expected_comments[0].model_dump(mode="json")
    candidates = [{"id": "F001", "comment": comment}, {"id": "F002", "comment": comment}]
    scores = voting.score_subsets(entry, candidates, {"B": ["F002"]}, [True, False])
    assert scores["B"]["tp"] == 0
    assert scores["B"]["fp"] == 1


def test_macro_uses_benchmark_population_conventions(entry):
    comment = entry.expected_comments[0].model_dump(mode="json")
    positive_silent = voting.score_subsets(entry, [], {"A": []}, [])["A"]
    positive_fp = voting.score_subsets(entry, [{"id": "F001", "comment": comment}], {"A": ["F001"]}, [False])["A"]
    clean_silent = voting.score_subsets(entry.model_copy(update={"expected_comments": []}), [], {"A": []}, [])["A"]
    summary = voting.metrics([{"scores": {"A": s}} for s in (positive_silent, positive_fp, clean_silent)], "A")
    assert summary["macro_denominators"] == {"precision": 2, "recall": 2, "f1": 3}
    assert summary["macro"]["precision"] == 0.5
    assert summary["macro"]["recall"] == 0


def test_start_marker_is_exclusive(tmp_path):
    voting.start_once(tmp_path)
    with pytest.raises(FileExistsError):
        voting.start_once(tmp_path)


def test_baseline_pin_models_and_planned_process_completeness(tmp_path):
    manifest = {
        "status": "completed",
        "engine": {"commit": voting.ENGINE},
        "bcquality": {"commit": voting.KNOWLEDGE},
        "configuration": {
            "root_model": voting.ROOT_MODEL,
            "leaf_model": voting.LEAF_MODEL,
            "copilot_cli_version": voting.CLI,
            "leaf_execution": "serial",
            "max_leaf_concurrency": 4,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
        },
        "plan": {"leaf_count": 1, "leaf_ids": ["test-leaf"]},
        "processes": [
            {"role": role, "skill_id": "test-leaf", "requested_model": model, "observed_models": [model], "status": "completed"}
            for role, model in (("leaf", voting.LEAF_MODEL), ("root", voting.ROOT_MODEL))
        ],
    }
    voting.save(tmp_path / "_run-manifest.json", manifest)
    voting.validate_baseline(tmp_path)
    manifest["processes"].pop(0)
    voting.save(tmp_path / "_run-manifest.json", manifest)
    with pytest.raises(ValueError, match="planned processes"):
        voting.validate_baseline(tmp_path)


def test_context_is_gold_blind_and_no_copy_preparation(tmp_path, monkeypatch):
    source, knowledge, folder = (tmp_path / p for p in ("source", "knowledge", "voter"))
    source.mkdir()
    knowledge.mkdir()
    (source / "example.al").write_text("code")
    monkeypatch.setattr(voting.shutil, "copytree", lambda *a, **k: pytest.fail("No whole-tree copies"))
    monkeypatch.setattr(voting.CodeReviewPipeline, "setup_workspace", lambda *a: pytest.fail("No repeated preparation"))
    monkeypatch.setattr(voting, "resolve_evidence", lambda *a, **k: [resolved()])

    def invoke(*args):
        context = voting.read(folder / "context/context.json")
        assert set(context) == {"source_root", "knowledge_root", "changed_paths", "patch", "base_commit"}
        assert sorted(p.name for p in (folder / "context").iterdir()) == ["candidates.json", "context.json"]
        (folder / "stdout.jsonl").write_text("")
        return json.dumps([resolved().decision.model_dump(mode="json")])

    monkeypatch.setattr(voting, "invoke_once", invoke)
    voting.verify_candidate_set(folder, source, knowledge, {"changed_paths": ["example.al"], "patch": "fixture", "base_commit": "a" * 40}, [{"id": "F001", "comment": {}}])


def test_shared_credentials_fail_before_invocation(tmp_path):
    source, knowledge = tmp_path / "source", tmp_path / "knowledge"
    (source / ".git").mkdir(parents=True)
    knowledge.mkdir()
    (source / ".git/config").write_text("[http]\nextraheader = fixture")
    with pytest.raises(ValueError, match="credentials"):
        voting.read_guards(source, knowledge, [])


def test_ignored_edges_remain_neutral(entry):
    comment = entry.expected_comments[0]
    ignored_entry = entry.model_copy(update={"expected_comments": [], "ignored_comments": [comment]})
    scores = voting.score_subsets(ignored_entry, [{"id": "F001", "comment": comment.model_dump(mode="json")}], {"A": ["F001"]}, [True])
    assert scores["A"]["ignored"] == 1
    assert scores["A"]["fp"] == 0


def test_one_baseline_three_serial_voters_one_judge_graph(tmp_path, monkeypatch, entry, baseline_fixture):
    source, baseline = baseline_fixture
    calls = []
    monkeypatch.setattr(voting, "verify_candidate_set", lambda folder, *a: calls.append(folder.name) or [resolved()])
    monkeypatch.setattr(voting, "judge_once", lambda *a: calls.append("judge") or [True])
    result = voting.run_entry(entry, source, tmp_path / "output", baseline)
    assert calls == ["voter-1", "voter-2", "voter-3", "judge"]
    assert result["operational_success"]
    assert result["scores"]["A"]["tp"] == result["scores"]["B"]["tp"] == result["scores"]["C"]["tp"] == 1
    with pytest.raises(FileExistsError):
        voting.run_entry(entry, source, tmp_path / "output", baseline)


def test_failed_verification_preserves_baseline_scoring_no_retry(tmp_path, monkeypatch, entry, baseline_fixture):
    source, baseline = baseline_fixture
    calls = []

    def fail(folder, *args):
        calls.append(folder.name)
        raise ValueError("invalid verdict")

    monkeypatch.setattr(voting, "verify_candidate_set", fail)
    monkeypatch.setattr(voting, "judge_once", lambda *a: [True])
    result = voting.run_entry(entry, source, tmp_path / "out", baseline)
    assert calls == ["voter-1"]
    assert result["baseline_scored"]
    assert not result["paired"]
    assert list(result["scores"]) == ["A"]


def test_invalid_evidence_is_exclusion_not_negative_vote(tmp_path, monkeypatch, entry, baseline_fixture):
    source, baseline = baseline_fixture
    monkeypatch.setattr(voting, "verify_candidate_set", lambda *a: [resolved(validity="unresolved")])
    monkeypatch.setattr(voting, "judge_once", lambda *a: [True])
    result = voting.run_entry(entry, source, tmp_path / "out", baseline)
    assert not result["paired"]
    assert result["scores"]["A"]["tp"] == 1


def test_no_candidates_skips_voters_and_does_not_prove_smoke(tmp_path, monkeypatch, entry, baseline_fixture):
    source, _ = baseline_fixture
    monkeypatch.setattr(voting, "verify_candidate_set", lambda *a: pytest.fail("No candidate calls"))
    monkeypatch.setattr(voting, "judge_once", lambda *a: [])
    result = voting.run_entry(entry, source, tmp_path / "out", lambda folder: voting.save(source / "review.json", []))
    assert result["operational_success"]
    summary = voting.summarize({"phase": "smoke", "selected": [entry.instance_id], "config": voting.config()}, tmp_path / "out")
    assert not summary["smoke_gate_passed"]


def test_failure_exports_diagnostics_and_other_entry_can_continue(tmp_path, monkeypatch, entry, baseline_fixture):
    source, baseline = baseline_fixture

    def fail(folder):
        voting.save(folder / "_run-manifest.json", {"status": "failed"})
        raise ValueError("baseline failure")

    failed = voting.run_entry(entry, source, tmp_path / "first", fail)
    assert not failed["baseline_complete"]
    assert (tmp_path / "first/baseline/_run-manifest.json").is_file()
    runtime2 = tmp_path / "runtime2"
    runtime2.mkdir()
    monkeypatch.setattr(voting.tempfile, "mkdtemp", lambda **k: str(runtime2))
    monkeypatch.setattr(voting, "verify_candidate_set", lambda *a: [resolved()])
    monkeypatch.setattr(voting, "judge_once", lambda *a: [True])
    assert voting.run_entry(entry, source, tmp_path / "second", baseline)["operational_success"]


def test_artifacts_exclude_auth_homes_checkouts_and_arbitrary_logs(tmp_path):
    runtime, output = tmp_path / "runtime", tmp_path / "artifacts"
    for name in ("baseline/_run-manifest.json", "voter-1/stdout.jsonl", "voter-1/context/context.json", "judge/edges.json"):
        voting.save(runtime / name, {})
    for name in ("voter-1/home/config.json", "baseline/bcquality/private.json", "baseline/trusted/.git/config", "voter-1/logs/credentials.json", "secret.txt"):
        voting.save(runtime / name, {"secret": "fixture"})
    voting.export_artifacts(runtime, output)
    assert sorted(str(p.relative_to(output)).replace("\\", "/") for p in output.rglob("*") if p.is_file()) == [
        "baseline/_run-manifest.json",
        "credential-redactions.json",
        "judge/edges.json",
        "voter-1/context/context.json",
        "voter-1/stdout.jsonl",
    ]


def test_known_process_credentials_are_not_published(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-sensitive-token")
    runtime, output = tmp_path / "runtime", tmp_path / "output"
    voting.save(runtime / "voter-1/stdout.jsonl", {"content": "fixture-sensitive-token"})
    voting.export_artifacts(runtime, output)
    assert "fixture-sensitive-token" not in (output / "voter-1/stdout.jsonl").read_text()
    assert voting.read(output / "credential-redactions.json")["paths"]


def test_missing_entries_and_failed_usage_remain_visible(tmp_path):
    voting.save(tmp_path / "case/baseline/started.json", {})
    summary = voting.summarize({"phase": "full", "selected": ["missing"], "config": voting.config()}, tmp_path)
    assert summary["missing"] == ["missing"]
    assert not summary["operational_success"]
    assert not summary["usage_complete"]
    assert summary["paired_arms"]["A"]["micro"] is None


def test_read_only_cli_arguments_and_clean_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("ADO_TOKEN", "must-not-propagate")
    monkeypatch.setenv("BRAINTRUST_API_KEY", "must-not-propagate")
    monkeypatch.setattr(voting, "parse_output", lambda _: (None, "[]"))
    folder = tmp_path / "voter-1"
    roots = (tmp_path / "source", tmp_path / "knowledge")
    for root in roots:
        root.mkdir()

    def process(args, **kwargs):
        assert "--available-tools=view,rg,glob" in args
        assert "--deny-tool=write" in args
        assert "--deny-tool=shell" in args
        assert "--disallow-temp-dir" in args
        assert [a for a in args if a.startswith("--add-dir=")] == [f"--add-dir={p}" for p in roots]
        assert kwargs["cwd"] == folder / "context"
        assert kwargs["timeout"] == 1800
        assert not {"ADO_TOKEN", "BRAINTRUST_API_KEY"} & kwargs["env"].keys()
        voting.save(folder / "usage.json", {"totalNanoAiu": 1, "modelMetrics": {voting.ROOT_MODEL: {"usage": {"inputTokens": 1, "outputTokens": 1}}}})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", process)
    assert voting.invoke_once(folder, voting.ROOT_MODEL, "fixture", roots) == "[]"
    assert (folder / "started.json").is_file()


def test_workflow_limits_retention_no_publication_and_failure_summary():
    path = Path(".github/workflows/pr-review-voting.yml")
    data = yaml.safe_load(path.read_text())
    evaluate = data["jobs"]["evaluate"]
    assert evaluate["runs-on"] == "ubuntu-latest"
    assert evaluate["strategy"]["max-parallel"] == 64
    assert evaluate["strategy"]["fail-fast"] is False
    assert "always()" in data["jobs"]["summarize"]["if"]
    text = path.read_text()
    assert "requeue" not in text
    assert "bceval" not in text
    assert "git push" not in text
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in text
    for job in data["jobs"].values():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                assert step["with"]["retention-days"] == 30
    parent = Path(".github/workflows/pr-review-evaluation.yml").read_text()
    assert "inputs.voting-phase == 'off'" in parent
    assert voting.ENGINE in text
    assert voting.CLI in text
