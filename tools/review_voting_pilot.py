"""Bounded live-view voting experiment (not protocol-equivalent to v1 or v2).

--prepare --root ROOT --cli EXE: fetch frozen dependencies and prepare six cases;
no inference. Requires a local engine-supported CLI (see EXPERIMENT.md).
--preflight --root ROOT: local versions/hashes/config checks only, no inference.
--execute --root ROOT: separately authorized paid run, at most 6 baseline reviews,
18 independent verifiers and one fixed-judge batch per case. Never retries or publishes.
--root alone fails rather than silently starting inference.

Verifiers use standard policy-filtered live view/rg/glob. No external capture
producer, raw-text prompt injection or raw-disk citation fallback. Unresolvable
read views are explicit exclusions, not negative votes. Baseline coverage and
complete-case A/B/C comparisons have separate denominators.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bcbench_core.scoring import f1_score, precision_recall

from bcbench.agent.copilot.metrics import parse_output
from bcbench.agent.pr_review.agent import _prepare_bcquality_root, get_pr_review_version, run_pr_review_agent
from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.codereview_judge import judge_verdicts
from bcbench.exceptions import AgentError, LLMJudgeError
from bcbench.results.codereview import assign_comment_matches, candidate_comment_pairs
from bcbench.types import EvaluationCategory
from tools.review_voting_evidence import (
    ADAPTER_VERSION,
    PROMPT_VERSION,
    ResolvedDecision,
    aggregate,
    digest_json,
    evidence_prompt,
    resolve_evidence,
    tree_digest,
    validate_votes,
)

MODEL = "gpt-5.6-sol"
JUDGE = "gpt-5.3-codex"
CONFIG_PATH = Path(__file__).with_name("review_voting_config.json")
logger = logging.getLogger(__name__)


class Candidate(TypedDict):
    id: str
    comment: dict[str, Any]


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_snapshot(root: Path, expected: str) -> None:
    if tree_digest(root) != expected:
        raise ValueError("Source/knowledge/input snapshot was altered")


def command(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr}")
    return result.stdout.strip()


def start_once(folder: Path) -> float:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "started.json").open("x", encoding="utf-8") as stream:
        json.dump({"started_unix": time.time(), "policy": "one attempt, never retry"}, stream)
    return time.monotonic()


def isolated_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("COPILOT_", "BCQUALITY_", "GITHUB_", "REVIEW_", "AGENT_", "OTEL_", "MINIMUM_SEVERITY", "MAX_FINDINGS"))}
    token = os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("Missing COPILOT_GITHUB_TOKEN/GH_TOKEN; no model call attempted")
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        COPILOT_HOME=str(home / ".copilot"),
        COPILOT_GITHUB_TOKEN=token,
        GH_TOKEN=token,
        CI="true",
        COPILOT_AUTO_UPDATE="false",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="BC-Bench local pilot",
        GIT_AUTHOR_EMAIL="bcbench-pilot@example.invalid",
        GIT_COMMITTER_NAME="BC-Bench local pilot",
        GIT_COMMITTER_EMAIL="bcbench-pilot@example.invalid",
    )
    return env


def run_verifier(
    folder: Path,
    source: Path,
    knowledge: Path,
    context: dict[str, Any],
    candidates: list[Candidate],
    cli: str,
) -> list[ResolvedDecision]:
    candidate_ids = [c["id"] for c in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Duplicate candidate IDs")
    if not candidate_ids:
        return []
    start = start_once(folder)
    work = folder / "work"
    work.mkdir()
    shutil.copytree(source, work / "source", ignore=shutil.ignore_patterns(".git"))
    shutil.copytree(knowledge, work / "knowledge", ignore=shutil.ignore_patterns(".git"))
    save(work / "candidates.json", candidates)
    save(work / "context.json", context)
    before = tree_digest(work)
    prompt = evidence_prompt()
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    args = [
        cli,
        "--no-auto-update",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--available-tools=view,rg,glob",
        "--allow-all-tools",
        "--no-ask-user",
        "--disallow-temp-dir",
        "--no-remote",
        "--no-remote-export",
        "--output-format=json",
        "--model=" + MODEL,
        "--context=default",
        "--usage-output-file",
        str(folder / "usage.json"),
        "--log-dir",
        str(folder / "logs"),
        "--prompt",
        prompt,
    ]
    save(
        folder / "invocation.json",
        {
            "args": args,
            "cwd": str(work),
            "model": MODEL,
            "adapter_version": ADAPTER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "input_sha256": before,
            "candidate_sha256": digest_json(candidates),
            "adapter_sha256": sha(Path(__file__)),
            "evidence_adapter_sha256": sha(Path(__file__).with_name("review_voting_evidence.py")),
        },
    )
    with (folder / "stdout.jsonl").open("w", encoding="utf-8") as out, (folder / "stderr.txt").open("w", encoding="utf-8") as err:
        try:
            completed = subprocess.run(args, cwd=work, env=isolated_environment(folder / "home"), stdout=out, stderr=err, timeout=1800, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            save(folder / "process.json", {"status": "failed", "error_type": type(exc).__name__, "wall_seconds": time.monotonic() - start})
            raise
    save(folder / "process.json", {"exit_code": completed.returncode, "wall_seconds": time.monotonic() - start})
    if completed.returncode:
        raise RuntimeError(f"Verifier failed with exit {completed.returncode}: {folder}")
    metrics, response = parse_output((folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines())
    (folder / "final.txt").write_text(response or "", encoding="utf-8")
    if metrics is not None:
        save(folder / "parsed-metrics.json", metrics.model_dump(mode="json"))
    try:
        decisions = validate_votes(candidate_ids, json.loads(response or ""))
        check_snapshot(work, before)
        events = [json.loads(line) for line in (folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        resolved = resolve_evidence(decisions, events, work)
    except (ValueError, TypeError, OSError) as exc:
        save(folder / "validation-failure.json", {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)})
        raise
    save(folder / "decisions.json", [d.model_dump(mode="json") for d in resolved])
    return resolved


def score_arms(entry: CodeReviewEntry, candidates: list[Candidate], arms: dict[str, list[str]], folder: Path) -> dict[str, dict[str, Any]]:
    generated = [ReviewComment.model_validate(c["comment"]) for c in candidates]
    keys = {id(comment): c["id"] for comment, c in zip(generated, candidates, strict=True)}
    expected = candidate_comment_pairs(entry.expected_comments, generated)
    ignored = candidate_comment_pairs(entry.ignored_comments, generated)
    folder.mkdir(parents=True, exist_ok=True)
    if expected or ignored:
        start_once(folder)
    verdicts = judge_verdicts(expected + ignored, folder, model=JUDGE)
    save(
        folder / "edges.json",
        [
            {"gold_bucket": "expected" if n < len(expected) else "ignored", "gold": gold.model_dump(mode="json"), "candidate_id": keys[id(candidate)], "match": match}
            for n, ((gold, candidate), match) in enumerate(zip(expected + ignored, verdicts, strict=True))
        ],
    )
    accepted_expected = [pair for pair, verdict in zip(expected, verdicts[: len(expected)], strict=True) if verdict]
    accepted_ignored = [pair for pair, verdict in zip(ignored, verdicts[len(expected) :], strict=True) if verdict]
    result = {}
    for name, selected in arms.items():
        matches, neutrals = assign_comment_matches(
            [pair for pair in accepted_expected if keys[id(pair[1])] in selected],
            [pair for pair in accepted_ignored if keys[id(pair[1])] in selected],
        )
        precision, recall = precision_recall(len(matches), len(selected) - len(neutrals), len(entry.expected_comments))
        result[name] = {
            "generated": len(selected),
            "expected": len(entry.expected_comments),
            "matched": len(matches),
            "ignored": len(neutrals),
            "false": len(selected) - len(neutrals) - len(matches),
            "missed": len(entry.expected_comments) - len(matches),
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
            "matched_ids": [keys[id(c)] for _, c in matches],
            "ignored_ids": [keys[id(c)] for _, c in neutrals],
        }
    return result


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if len(config["cases"]) != 6 or len(set(config["cases"])) != 6:
        raise ValueError("Exactly six unique preselected cases required")
    if config["verifier_model"] != MODEL or config["judge_model"] != JUDGE or config["protocol"] != ADAPTER_VERSION:
        raise ValueError("Experiment protocol/model mismatch")
    for key in ("engine_sha", "bcquality_sha"):
        if re.fullmatch(r"[0-9a-f]{40}", config[key]) is None:
            raise ValueError("Immutable full engine and BCQuality SHAs required")
    return config


def selected_entries(benchmark: Path, config: dict[str, Any]) -> list[CodeReviewEntry]:
    entries = {e.instance_id: e for e in CodeReviewEntry.load(benchmark / "dataset" / "codereview.jsonl")}
    return [entries[key] for key in config["cases"]]


def checkout_commit(path: Path, repository: str, commit: str) -> None:
    path.mkdir(parents=True)
    command(["git", "init", "--quiet"], path)
    command(["git", "config", "core.longpaths", "true"], path)
    command(["git", "config", "core.autocrlf", "false"], path)
    command(["git", "remote", "add", "origin", repository], path)
    command(["git", "fetch", "--quiet", "--depth=1", "origin", commit], path)
    command(["git", "checkout", "--quiet", "--detach", commit], path)


def probe_cli(cli: Path, config: dict[str, Any]) -> dict[str, str]:
    if not cli.is_file():
        raise ValueError("CLI executable missing. Install @github/copilot@1.0.88 locally and pass its native copilot.exe to --prepare --cli.")
    version = command([str(cli), "--no-auto-update", "--version"])
    match = re.search(r"^GitHub Copilot CLI (\S+)\.$", version, re.MULTILINE)
    if match is None or match[1] != config["cli_version"]:
        raise ValueError(f"Required engine-supported CLI {config['cli_version']}; observed {version}")
    help_text = command([str(cli), "--no-auto-update", "--help"])
    for flag in ("--available-tools", "--no-custom-instructions", "--disable-builtin-mcps", "--usage-output-file", "--disallow-temp-dir", "--no-remote-export"):
        if flag not in help_text:
            raise ValueError(f"Installed CLI lacks {flag}")
    return {"path": str(cli), "sha256": sha(cli), "version": version}


def implementation_identity(benchmark: Path) -> dict[str, str]:
    if command(["git", "status", "--porcelain"], benchmark):
        raise ValueError("Commit the experiment implementation before freezing a new preparation")
    return {
        "benchmark_commit": command(["git", "rev-parse", "HEAD"], benchmark),
        "dataset_sha256": sha(benchmark / "dataset" / "codereview.jsonl"),
        "adapter_sha256": sha(Path(__file__)),
        "evidence_adapter_sha256": sha(Path(__file__).with_name("review_voting_evidence.py")),
        "config_sha256": sha(CONFIG_PATH),
        "shared_config_sha256": sha(benchmark / "src" / "bcbench" / "agent" / "shared" / "config.yaml"),
    }


def prepare(root: Path, benchmark: Path, cli: Path) -> None:
    config = load_config()
    cli_identity = probe_cli(cli, config)
    if root.exists():
        raise FileExistsError("Preparation requires a fresh root; never overwrite historical or partial artifacts")
    root.mkdir(parents=True)
    entries = selected_entries(benchmark, config)
    save(root / "selection.json", {"config": config, **implementation_identity(benchmark), "cli": cli_identity})
    checkout_commit(root / "engine", "https://github.com/microsoft/BC-ALAgents", config["engine_sha"])
    knowledge = _prepare_bcquality_root(root / "engine", "pwsh", root / "knowledge")
    targets = {(repo, base): root / "targets" / f"base-{n:02}" for n, (repo, base) in enumerate(sorted({(entry.repo, entry.base_commit) for entry in entries}), 1)}
    for (repo, base), target in targets.items():
        checkout_commit(target, f"https://github.com/{repo}", base)
        command(["git", "update-ref", "refs/heads/pilot-base", base], target)
    identities = []
    for n, entry in enumerate(entries, 1):
        source = root / "prepared" / f"case-{n:02}" / "source"
        source.parent.mkdir(parents=True)
        command(["git", "clone", "--quiet", "--shared", "--no-checkout", str(targets[(entry.repo, entry.base_commit)]), str(source)])
        command(["git", "config", "core.longpaths", "true"], source)
        command(["git", "config", "core.autocrlf", "false"], source)
        command(["git", "checkout", "--quiet", "--detach", entry.base_commit], source)
        CodeReviewPipeline().setup_workspace(entry, source)
        identities.append(tree_digest(source))
    save(root / "inputs.json", {"source_sha256": identities, "knowledge_sha256": tree_digest(knowledge)})
    save(root / "preflight.json", preflight(root, benchmark))


def preflight(root: Path, benchmark: Path) -> dict[str, Any]:
    config = load_config()
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    if selection["config"] != config or any(selection[key] != value for key, value in implementation_identity(benchmark).items()):
        raise ValueError("Frozen selection/implementation changed; prepare a fresh root")
    if get_pr_review_version(root / "engine") != config["engine_sha"]:
        raise ValueError("Engine checkout must be clean at the frozen experiment SHA")
    declared = yaml.safe_load((root / "engine" / "agents" / "ALReviewAgent" / "bcquality.config.yaml").read_text(encoding="utf-8"))
    if declared["bcquality"]["ref"] != config["bcquality_sha"]:
        raise ValueError("Engine-declared BCQuality pin mismatch")
    if command(["git", "rev-parse", "HEAD"], root / "knowledge") != config["bcquality_sha"]:
        raise ValueError("Prepared BCQuality identity mismatch")
    policy = root / "engine" / "agents" / "ALReviewAgent" / "copilot-cli-compatibility.psd1"
    command(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            (
                f"$p=Import-PowerShellDataFile -LiteralPath '{str(policy).replace(chr(39), chr(39) * 2)}'; "
                f"if (-not $p.supported_versions.ContainsKey('{config['cli_version']}')) {{ throw 'Unsupported CLI' }}; "
                "if (-not (Get-Module -ListAvailable powershell-yaml)) { throw 'Install powershell-yaml before execution' }; "
                "if (-not (Get-Command Test-Json -ErrorAction SilentlyContinue)) { throw 'PowerShell Test-Json missing' }; "
                "$PSVersionTable.PSVersion.ToString()"
            ),
        ]
    )
    cli = probe_cli(Path(selection["cli"]["path"]), config)
    if cli != selection["cli"]:
        raise ValueError("Frozen CLI identity changed")
    inputs = json.loads((root / "inputs.json").read_text(encoding="utf-8"))
    entries = selected_entries(benchmark, config)
    observed = [tree_digest(root / "prepared" / f"case-{n:02}" / "source") for n in range(1, 7)]
    if inputs != {"source_sha256": observed, "knowledge_sha256": tree_digest(root / "knowledge")}:
        raise ValueError("Prepared source/knowledge snapshot changed")
    for n, entry in enumerate(entries, 1):
        source = root / "prepared" / f"case-{n:02}" / "source"
        if command(["git", "rev-parse", "HEAD"], source) != entry.base_commit:
            raise ValueError("Prepared base revision mismatch")
        command(["git", "cat-file", "-e", entry.base_commit + "^{commit}"], source)
        for line in entry.patch.splitlines():
            if line.startswith("+++ b/") and not (source / line[6:].strip()).is_file():
                raise ValueError("Prepared changed source file missing")
    if not any((root / "knowledge" / "microsoft" / "knowledge").rglob("*.md")):
        raise ValueError("No engine-pinned knowledge articles available")
    return {
        "status": "offline_checks_passed",
        "config": config,
        "cli": cli,
        "credentials_present": bool(os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")),
        "paid_calls": 0,
        "limits": {"baseline": 6, "verifier": 18, "judge_batches": 6, "retries": 0},
        "unproven": ["model availability/authentication", "live read visibility and JSONL view shape", "baseline execution/telemetry", "semantic correctness"],
    }


def set_run_environment(original: dict[str, str], home: Path, selection: dict[str, Any]) -> None:
    os.environ.clear()
    os.environ.update(original)
    env = isolated_environment(home)
    config = selection["config"]
    env.update(
        PATH=str(Path(selection["cli"]["path"]).parent) + os.pathsep + env["PATH"],
        COPILOT_REVIEW_CLI_VERSION=config["cli_version"],
        COPILOT_REVIEW_LEAF_MODEL=config["leaf_model"],
        COPILOT_REVIEW_LEAF_EXECUTION=config["leaf_execution"],
        COPILOT_REVIEW_MAX_LEAF_CONCURRENCY=str(config["max_leaf_concurrency"]),
        MINIMUM_SEVERITY=config["minimum_severity"],
    )
    os.environ.clear()
    os.environ.update(env)


def failure(path: Path, exc: Exception) -> None:
    save(path, {"status": "failed", "type": type(exc).__name__, "message": str(exc)})
    logger.error("%s: %s", path, exc)


def summarize_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    def totals(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
        scores = [row["arms"][arm] for row in rows]
        counts = {key: sum(s[key] for s in scores) for key in ("generated", "expected", "matched", "ignored", "false", "missed")}
        precision, recall = precision_recall(counts["matched"], counts["generated"] - counts["ignored"], counts["expected"])
        return {"cases": len(rows), **counts, "micro_precision": precision if rows else None, "micro_recall": recall if rows else None, "micro_f1": f1_score(precision, recall) if rows else None}

    paired = [row for row in results if row["paired"]]
    return {
        "full_scored_baseline": totals(results, "A"),
        "complete_case_paired": {arm: totals(paired, arm) for arm in ("A", "B", "C")},
        "paired_instance_ids": [row["instance_id"] for row in paired],
        "warning": "Compare A/B/C only within complete_case_paired. Baseline and paired coverage are different denominators; exclusions are not improvements.",
    }


def case_arms(case: Path, source: Path, knowledge: Path, entry: CodeReviewEntry, candidates: list[Candidate], cli: str) -> tuple[dict[str, list[str]], str | None]:
    context = {"base_commit": entry.base_commit, "changed_paths": [line[6:].strip() for line in entry.patch.splitlines() if line.startswith("+++ b/")]}
    voters = []
    if candidates:
        for number in range(1, 4):
            folder = case / f"voter-{number}"
            try:
                voters.append(run_verifier(folder, source, knowledge, context, candidates, cli))
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
                failure(folder / "failure.json", exc)
                voters.append(None)
    try:
        return aggregate([c["id"] for c in candidates], voters), None
    except ValueError as exc:
        failure(case / "paired-exclusion.json", exc)
        return {"A": [c["id"] for c in candidates]}, str(exc)


def run(root: Path, benchmark: Path) -> None:
    if (root / "execution").exists() or any((root / f"case-{n:02}").exists() for n in range(1, 7)):
        raise FileExistsError("One-shot execution requires fresh outputs; historical/partial runs cannot be retried")
    checks = preflight(root, benchmark)
    if not checks["credentials_present"]:
        raise RuntimeError("Set GH_TOKEN or COPILOT_GITHUB_TOKEN before --execute; credentials were not probed by inference")
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    config = selection["config"]
    entries = selected_entries(benchmark, config)
    start = start_once(root / "execution")
    save(
        root / "metadata.json",
        {
            "selection": selection,
            "preflight": checks,
            "baseline_label": "Frozen deterministic-engine baseline",
            "ci_exact_reproduction": False,
            "workflow_cli_pin": "1.0.82",
            "observed_root_and_leaf_models": "Unknown until execution; retain each baseline's raw run manifest and metrics.",
        },
    )
    logging.basicConfig(filename=root / "driver.log", level=logging.INFO, encoding="utf-8")
    original_environment = dict(os.environ)
    completed = []
    exclusions = []
    try:
        for index, entry in enumerate(entries, 1):
            case = root / f"case-{index:02}"
            source = case / "source"
            shutil.copytree(root / "prepared" / f"case-{index:02}" / "source", source)
            save(case / "gold-private.json", entry.model_dump(mode="json"))
            baseline = case / "baseline"
            try:
                baseline_start = start_once(baseline)
                set_run_environment(original_environment, baseline / "home", selection)
                metrics, _ = run_pr_review_agent(
                    entry,
                    config["root_model"],
                    EvaluationCategory.CODE_REVIEW,
                    source,
                    baseline,
                    engine_path=root / "engine",
                    min_severity=config["agent_minimum_severity"],
                )
                save(baseline / "metrics.json", metrics.model_dump(mode="json"))
                save(baseline / "elapsed.json", {"seconds": time.monotonic() - baseline_start})
                raw = json.loads((source / "review.json").read_text(encoding="utf-8"))
                (source / "review.json").replace(case / "frozen-review.json")
                candidates = [Candidate(id=f"F{n:03}", comment=ReviewComment.model_validate(comment).model_dump(mode="json")) for n, comment in enumerate(raw, 1)]
                save(case / "candidates.json", candidates)
                # Verify the actual baseline source remained the prepared input.
                check_snapshot(source, tree_digest(root / "prepared" / f"case-{index:02}" / "source"))
                completed.append((entry, case, source, candidates))
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError, AgentError) as exc:
                failure(baseline / "failure.json", exc)
                exclusions.append({"instance_id": entry.instance_id, "stage": "baseline", "reason": str(exc)})
        results = []
        for entry, case, source, candidates in completed:
            set_run_environment(original_environment, case / "verification-home", selection)
            arms, excluded = case_arms(case, source, root / "knowledge", entry, candidates, selection["cli"]["path"])
            save(case / "arms.json", arms)
            if excluded:
                exclusions.append({"instance_id": entry.instance_id, "stage": "verification", "reason": excluded})
            try:
                set_run_environment(original_environment, case / "judge-home", selection)
                scores = score_arms(entry, candidates, arms, case / "judge")
                save(case / "scores.json", scores)
                save(
                    case / "candidate-labels.json",
                    {c["id"]: "TP" if c["id"] in scores["A"]["matched_ids"] else "ignored" if c["id"] in scores["A"]["ignored_ids"] else "FP" for c in candidates},
                )
                results.append({"instance_id": entry.instance_id, "paired": excluded is None, "arms": scores})
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError, LLMJudgeError) as exc:
                failure(case / "judge" / "failure.json", exc)
                exclusions.append({"instance_id": entry.instance_id, "stage": "judge", "reason": str(exc)})
        save(
            root / "results.json",
            {
                "cases": results,
                "exclusions": exclusions,
                "denominators": {"selected": 6, "baseline_completed": len(completed), "baseline_scored": len(results), "paired_scored": sum(1 for r in results if r["paired"])},
                "total_wall_seconds": time.monotonic() - start,
                "usage": "Per-stage metrics/usage files; missing or incomplete usage is unknown, never zero.",
                "summary": summarize_scores(results),
            },
        )
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true", help="Prepare fixed source/engine/knowledge; no inference")
    modes.add_argument("--preflight", action="store_true", help="Offline runtime checks only; no inference")
    modes.add_argument("--execute", action="store_true", help="Explicit paid execution; requires separate approval")
    parser.add_argument("--cli", type=Path, help="Native engine-supported executable; required only for preparation")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    benchmark = Path(__file__).resolve().parents[1]
    if arguments.prepare:
        if not arguments.cli:
            parser.error("--prepare requires --cli pointing to a supported native executable")
        prepare(root, benchmark, arguments.cli.resolve())
    elif arguments.cli:
        parser.error("--cli can only be set when freezing preparation")
    elif arguments.preflight:
        print(json.dumps(preflight(root, benchmark), indent=2))
    else:
        run(root, benchmark)


if __name__ == "__main__":
    main()
