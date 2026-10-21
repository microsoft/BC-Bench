"""Artifact-only, one-generation A/B/C experiment; no retries or publication."""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from bcbench_core.scoring import f1_score, precision_recall

from bcbench.agent.copilot.metrics import parse_output
from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.codereview_judge import _format_pair
from bcbench.evaluate.review_verification import RESOLVER_VERSION, SHARED_ROOTS_PROMPT_VERSION, ResolvedDecision, aggregate, digest_json, evidence_prompt, resolve_evidence, validate_votes
from bcbench.results.codereview import assign_comment_matches, candidate_comment_pairs

logger = logging.getLogger(__name__)
ENGINE = "9607dea1c84fcf660983a5e3791dece1fb2f1623"
KNOWLEDGE = "b74967bc5b7a454eae19d6a1250199afd869f064"
CLI = "1.0.88"
ROOT_MODEL = "gpt-5.6-sol"
LEAF_MODEL = "gpt-5.6-luna"
JUDGE = "gpt-5.3-codex"
DATASET_COMMIT = "7c98b750c200d88ed0a81daaea5e71184a3af01b"
DATASET_SHA256 = "43bcddc685e3f81cb655fc0efe33f7c47763fe64864ecf62ab69220a231e513c"
SMOKE = ("synthetic__errh-tryfunction-swallowed-01", "synthetic__get-clean-01")
Phase = Literal["smoke", "full"]


def read(path: Path) -> Any:  # noqa: ANN401 - Persisted artifact schemas include arrays and objects.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def config() -> dict[str, Any]:
    return {
        "protocol": "formal-voting-v1",
        "engine_sha": ENGINE,
        "bcquality_sha": KNOWLEDGE,
        "cli_version": CLI,
        "root_model": ROOT_MODEL,
        "leaf_model": LEAF_MODEL,
        "leaf_execution": "serial",
        "max_leaf_concurrency": 4,
        "minimum_severity": "Medium",
        "agent_minimum_severity": "Medium",
        "verifier_model": ROOT_MODEL,
        "judge_model": JUDGE,
        "resolver_version": RESOLVER_VERSION,
        "prompt_version": SHARED_ROOTS_PROMPT_VERSION,
        "prompt_sha256": digest_json(evidence_prompt(shared_roots=True)),
        "dataset_commit": DATASET_COMMIT,
        "dataset_sha256": DATASET_SHA256,
        "voters": 3,
        "single_voter": 1,
        "supported_threshold": 2,
        "retries": 0,
        "publish": False,
    }


def plan(dataset: Path, phase: Phase) -> dict[str, Any]:
    if file_hash(dataset) != DATASET_SHA256:
        raise ValueError("Dataset differs from the approved immutable 145-case selection")
    entries = CodeReviewEntry.load(dataset)
    if len(entries) != 145 or sum(bool(e.expected_comments) for e in entries) != 106:
        raise ValueError("Unexpected dataset population")
    selected = [e.instance_id for e in entries] if phase == "full" else list(SMOKE)
    by_id = {e.instance_id: e for e in entries}
    if not by_id[SMOKE[0]].expected_comments or by_id[SMOKE[1]].expected_comments:
        raise ValueError("Smoke requires the preselected positive and empty-gold cases")
    return {
        "phase": phase,
        "experiment_revision": os.environ.get("GITHUB_SHA"),
        "selected": selected,
        "config": config(),
        "config_sha256": digest_json(config()),
        "budgets": {"reviews": len(selected), "verifiers": len(selected) * 3, "judge_batches": 106 if phase == "full" else 2},
        "success_criteria": [
            "Valid completed baseline with exact observed engine, knowledge, CLI, root and leaf models",
            "Smoke has nonempty frozen candidates in BOTH cases so all six voter invocations are exercised",
            "Every applicable voter returns all IDs, resolved source and knowledge evidence, and the pinned observed model",
            "Every required judge pair has one strict Boolean verdict, no missing or duplicate pairs",
            "A/B/C scores and artifacts exist; no desired reduction or clean-case silence requirement",
            "Selected, completed baseline, scored baseline and complete-paired denominators remain separate",
        ],
    }


def checked_command(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60).stdout.strip()


def start_once(folder: Path) -> float:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "started.json").open("x", encoding="utf-8") as stream:
        json.dump({"unix": time.time(), "pid": os.getpid(), "retry": False}, stream)
    return time.monotonic()


def read_guards(source: Path, knowledge: Path, changed: list[str]) -> dict[str, Any]:
    result = {}
    for label, root in (("source", source), ("knowledge", knowledge)):
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Shared roots must be real directories")
        for relative in (".github/hooks", ".github/extensions", ".github/copilot/settings.json", ".github/copilot/settings.local.json", ".mcp.json"):
            if (root / relative).exists():
                raise ValueError(f"Shared root contains auto-loaded configuration: {relative}")
        info = root.stat()
        result[label] = {"path": str(root), "device": info.st_dev, "inode": info.st_ino}
        git_config = root / ".git/config"
        if git_config.is_file() and re.search(r"extraheader|credential|https?://[^/\s]+@", git_config.read_text(encoding="utf-8"), re.IGNORECASE):
            raise ValueError("Shared root Git configuration may expose credentials")
    if any(not (source / p).resolve().is_relative_to(source.resolve()) for p in changed):
        raise ValueError("Changed path escapes shared source root")
    result["changed"] = {p: file_hash(source / p) for p in changed}
    return result


def isolated_environment(home: Path) -> dict[str, str]:
    # Only the required token is passed, never Azure/Braintrust/Kusto credentials.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "PATHEXT",
            "SystemRoot",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS",
        }
    }
    token = os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Missing Copilot credentials before invocation")
    env.update(HOME=str(home), USERPROFILE=str(home), COPILOT_HOME=str(home / ".copilot"), COPILOT_GITHUB_TOKEN=token, GH_TOKEN=token, CI="true", COPILOT_AUTO_UPDATE="false", GIT_TERMINAL_PROMPT="0")
    save(home / ".copilot/config.json", {"disableAllHooks": True, "memory": False, "ide": {"autoConnect": False}, "trustedFolders": []})
    return env


def invoke_once(folder: Path, model: str, prompt: str, roots: tuple[Path, ...] = ()) -> str:
    work = folder / "context"
    work.mkdir(parents=True, exist_ok=True)
    if any(folder.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(folder.resolve()) for p in roots):
        raise ValueError("Allowed source roots must exclude vote outputs and homes")
    env = isolated_environment(folder / "home")
    args = [
        "copilot",
        "--no-auto-update",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--available-tools=view,rg,glob",
        "--allow-all-tools",
        "--deny-tool=write",
        "--deny-tool=shell",
        "--deny-tool=url",
        "--disallow-temp-dir",
        "--no-ask-user",
        "--no-remote",
        "--no-remote-export",
        "--output-format=json",
        f"--model={model}",
        "--context=default",
        "--usage-output-file",
        str(folder / "usage.json"),
        "--log-dir",
        str(folder / "logs"),
        *[f"--add-dir={p}" for p in roots],
        "--prompt",
        prompt,
    ]
    save(folder / "invocation.json", {"args": args, "cwd": str(work), "model": model, "config": config()})
    start = start_once(folder)
    try:
        with (folder / "stdout.jsonl").open("w", encoding="utf-8") as out, (folder / "stderr.txt").open("w", encoding="utf-8") as err:
            process = subprocess.run(args, cwd=work, env=env, stdout=out, stderr=err, timeout=1800, check=False)
        save(folder / "process.json", {"exit_code": process.returncode, "ended_unix": time.time(), "wall_seconds": time.monotonic() - start})
        if process.returncode:
            raise RuntimeError(f"CLI exited {process.returncode}")  # noqa: TRY301 - Keep a terminal failure receipt.
        _, response = parse_output((folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines())
        (folder / "final.txt").write_text(response or "", encoding="utf-8")
        usage = read(folder / "usage.json")
        models = set(usage["modelMetrics"])
        if models != {model}:
            raise ValueError(f"Observed models {models} do not equal requested {model}")  # noqa: TRY301 - Keep a terminal failure receipt.
        save(
            folder / "metrics.json",
            {"credits": usage["totalNanoAiu"] / 1e9, "tokens": sum(v["usage"]["inputTokens"] + v["usage"]["outputTokens"] for v in usage["modelMetrics"].values()), "observed_models": sorted(models)},
        )
    except Exception as exc:
        save(folder / "failure.json", {"error_type": type(exc).__name__, "reason": str(exc), "wall_seconds": time.monotonic() - start})
        raise
    else:
        return response or ""


def verify_candidate_set(folder: Path, source: Path, knowledge: Path, context: dict[str, Any], candidates: list[dict[str, Any]]) -> list[ResolvedDecision]:
    before = read_guards(source, knowledge, context["changed_paths"])
    save(folder / "context/candidates.json", candidates)
    save(folder / "context/context.json", context | {"source_root": str(source), "knowledge_root": str(knowledge)})
    inputs = {p.name: file_hash(p) for p in (folder / "context").iterdir()}
    response = invoke_once(folder, ROOT_MODEL, evidence_prompt(shared_roots=True), (source, knowledge))
    decisions = validate_votes([c["id"] for c in candidates], json.loads(response))
    if before != read_guards(source, knowledge, context["changed_paths"]) or inputs != {p.name: file_hash(p) for p in (folder / "context").iterdir()}:
        raise ValueError("Verifier changed its frozen inputs")
    events = [json.loads(line) for line in (folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(e["data"]["toolName"] not in {"view", "rg", "glob"} for e in events if e.get("type") == "tool.execution_start"):
        raise ValueError("Verifier used an unexpected tool")
    resolved = resolve_evidence(decisions, events, folder / "context", roots={"source": source, "knowledge": knowledge}, require_exact_reads=True)
    save(folder / "decisions.json", [r.model_dump(mode="json") for r in resolved])
    return resolved


def strict_judge_verdicts(response: str, count: int) -> list[bool]:
    raw = json.loads(response)
    if not isinstance(raw, list) or len(raw) != count:
        raise ValueError("Judge must return every pair exactly once")
    found = {}
    for row in raw:
        if not isinstance(row, dict) or type(row.get("pair")) is not int or type(row.get("match")) is not bool or row["pair"] in found:
            raise ValueError("Judge pairs require unique integer IDs and Boolean matches")
        found[row["pair"]] = row["match"]
    if set(found) != set(range(1, count + 1)):
        raise ValueError("Judge pair IDs missing or unknown")
    return [found[n] for n in range(1, count + 1)]


def score_subsets(entry: CodeReviewEntry, candidates: list[dict[str, Any]], arms: dict[str, list[str]], verdicts: list[bool]) -> dict[str, Any]:
    generated = [ReviewComment.model_validate(c["comment"]) for c in candidates]
    keys = {id(c): row["id"] for c, row in zip(generated, candidates, strict=True)}
    expected = candidate_comment_pairs(entry.expected_comments, generated)
    ignored = candidate_comment_pairs(entry.ignored_comments, generated)
    accepted = {(id(gold), id(candidate)) for (gold, candidate), ok in zip(expected + ignored, verdicts, strict=True) if ok}
    result = {}
    for arm, ids in arms.items():
        allowed = {id(c) for c in generated if keys[id(c)] in ids}
        ep = [p for p in expected if (id(p[0]), id(p[1])) in accepted and id(p[1]) in allowed]
        ip = [p for p in ignored if (id(p[0]), id(p[1])) in accepted and id(p[1]) in allowed]
        matches, neutrals = assign_comment_matches(ep, ip)
        precision, recall = precision_recall(len(matches), len(ids) - len(neutrals), len(entry.expected_comments))
        result[arm] = {
            "generated": len(ids),
            "expected": len(entry.expected_comments),
            "tp": len(matches),
            "fp": len(ids) - len(matches) - len(neutrals),
            "fn": len(entry.expected_comments) - len(matches),
            "ignored": len(neutrals),
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
            "matched_ids": [keys[id(c)] for _, c in matches],
        }
    return result


def judge_once(entry: CodeReviewEntry, candidates: list[dict[str, Any]], folder: Path) -> list[bool]:
    generated = [ReviewComment.model_validate(c["comment"]) for c in candidates]
    expected = candidate_comment_pairs(entry.expected_comments, generated)
    ignored = candidate_comment_pairs(entry.ignored_comments, generated)
    pairs = expected + ignored
    keys = {id(c): row["id"] for c, row in zip(generated, candidates, strict=True)}
    prompt = (
        "Determine whether each Expected/Candidate pair identifies the SAME underlying issue. Accept semantic matches, not merely nearby lines.\n"
        + "\n\n".join(_format_pair(n, gold, candidate) for n, (gold, candidate) in enumerate(pairs, 1))
        + '\nReturn ONLY a JSON array with exactly one {"pair": 1, "match": true, "reasoning": "..."} for every numbered pair. No tools, file writes or other prose.'
    )
    verdicts = strict_judge_verdicts(invoke_once(folder, JUDGE, prompt), len(pairs)) if pairs else []
    save(
        folder / "edges.json",
        [
            {"bucket": "expected" if n < len(expected) else "ignored", "gold": gold.model_dump(mode="json"), "candidate_id": keys[id(candidate)], "match": ok}
            for n, ((gold, candidate), ok) in enumerate(zip(pairs, verdicts, strict=True))
        ],
    )
    return verdicts


def validate_baseline(folder: Path) -> None:
    manifest = read(folder / "_run-manifest.json")
    wanted = {
        "root_model": ROOT_MODEL,
        "leaf_model": LEAF_MODEL,
        "copilot_cli_version": CLI,
        "leaf_execution": "serial",
        "max_leaf_concurrency": 4,
        "minimum_severity": "Medium",
        "agent_minimum_severity": "Medium",
    }
    if manifest["status"] != "completed" or manifest["engine"]["commit"] != ENGINE or manifest["bcquality"]["commit"] != KNOWLEDGE:
        raise ValueError("Baseline incomplete or dependency identity differs")
    if any(manifest["configuration"].get(k) != v for k, v in wanted.items()):
        raise ValueError("Baseline configuration differs")
    processes = manifest["processes"]
    leaves = [p for p in processes if p["role"] == "leaf"]
    if sum(p["role"] == "root" for p in processes) != 1 or len(leaves) != manifest["plan"]["leaf_count"] or {p["skill_id"] for p in leaves} != set(manifest["plan"]["leaf_ids"]):
        raise ValueError("Missing or duplicate baseline planned processes")
    if any(p["role"] not in {"root", "leaf"} for p in processes):
        raise ValueError("Unexpected baseline process role")
    for process in processes:
        model = ROOT_MODEL if process["role"] == "root" else LEAF_MODEL
        if process["status"] != "completed" or process["requested_model"] != model or set(process["observed_models"]) != {model}:
            raise ValueError("Baseline process missing, failed, or observed model differs")


ARTIFACT_NAMES = {
    "started.json",
    "failure.json",
    "process.json",
    "invocation.json",
    "metrics.json",
    "stdout.jsonl",
    "stderr.txt",
    "usage.json",
    "final.txt",
    "decisions.json",
    "candidates.json",
    "context.json",
    "edges.json",
    "_run-manifest.json",
    "_run-metrics.json",
    "_review-report.json",
    "al-code-review-findings.json",
    "agent-transcript.log",
    "agent-output.txt",
    "al-code-review-raw.txt",
    "_filter-report.json",
    "_task-context.json",
    "_review-source-bounds.json",
    "_review-diff.patch",
    "_review-changed-files.txt",
    "_copilot-otel.jsonl",
    "_leaf-report.json",
    "heartbeat.json",
}


def export_artifacts(runtime: Path, output: Path) -> None:
    # Do not enter auth homes, knowledge/source checkouts, .git, or arbitrary logs.
    credentials = {value for key, value in os.environ.items() if key.endswith(("_TOKEN", "_KEY", "_SECRET", "_PASSWORD")) and len(value) >= 8}
    redacted = []
    for root, dirs, files in os.walk(runtime, followlinks=False):
        parent = Path(root)
        dirs[:] = [d for d in dirs if not (parent / d).is_symlink() and (d in {"baseline", "judge", "context", "leaf-results"} or d.startswith(("voter-", "root-", "0", "1")))]
        for name in files:
            path = parent / name
            if name in ARTIFACT_NAMES and not path.is_symlink():
                dest = output / path.relative_to(runtime)
                dest.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                safe = data
                for value in credentials:
                    safe = safe.replace(value.encode("utf-8"), b"[credential-redacted]")
                if safe != data:
                    redacted.append(str(path.relative_to(runtime)))
                    dest.write_bytes(safe)
                else:
                    shutil.copyfile(path, dest)
    save(output / "credential-redactions.json", {"paths": redacted, "policy": "Known process credentials excluded; no hidden source recovery"})


def export_interrupted(output: Path) -> None:
    receipt = output / "runtime.json"
    if receipt.exists():
        runtime = Path(read(receipt)["path"])
        if runtime.parent != Path(tempfile.gettempdir()).resolve() or not runtime.name.startswith("bcbench-voting-"):
            raise ValueError("Unexpected runtime export path")
        export_artifacts(runtime, output)


def run_entry(entry: CodeReviewEntry, source: Path, output: Path, baseline_runner: Callable[[Path], None]) -> dict[str, Any]:
    start = start_once(output)
    runtime = Path(tempfile.mkdtemp(prefix="bcbench-voting-")).resolve()
    save(output / "runtime.json", {"path": str(runtime)})
    source = source.resolve()
    result: dict[str, Any] = {
        "instance_id": entry.instance_id,
        "config": config(),
        "baseline_complete": False,
        "baseline_scored": False,
        "paired": False,
        "operational_success": False,
        "candidates": None,
        "errors": [],
        "scores": {},
        "artifact_runtime": str(runtime),
    }
    try:
        CodeReviewPipeline().setup_workspace(entry, source)
        changed = [line[6:].strip() for line in entry.patch.splitlines() if line.startswith("+++ b/")]
        source_hashes = {p: file_hash(source / p) for p in changed}
        save(
            output / "provenance.json",
            {
                "config": config(),
                "base_commit": entry.base_commit,
                "patch_sha256": digest_json(entry.patch),
                "changed_file_sha256": source_hashes,
                "source_policy": "One prepared repository per matrix entry; no per-voter copy or recursive rehash",
                "experiment_revision": os.environ.get("GITHUB_SHA"),
                "workflow_run": os.environ.get("GITHUB_RUN_ID"),
            },
        )
        baseline = runtime / "baseline"
        start_once(baseline)
        baseline_start = time.monotonic()
        try:
            baseline_runner(baseline)
        finally:
            save(baseline / "process.json", {"ended_unix": time.time(), "wall_seconds": time.monotonic() - baseline_start})
        validate_baseline(baseline)
        if source_hashes != {p: file_hash(source / p) for p in changed}:
            raise ValueError("Baseline changed candidate source files")  # noqa: TRY301 - Persist failure before returning.
        raw = read(source / "review.json")
        candidates = [{"id": f"F{n:03}", "comment": ReviewComment.model_validate(c).model_dump(mode="json")} for n, c in enumerate(raw, 1)]
        (source / "review.json").unlink()
        save(runtime / "candidates.json", candidates)
        save(
            output / "frozen.json",
            {"candidate_sha256": digest_json(candidates), "patch_sha256": digest_json(entry.patch), "config_sha256": digest_json(config()), "changed_file_sha256": source_hashes},
        )
        result.update(baseline_complete=True, candidates=len(candidates))
        knowledge = baseline / "bcquality"
        context = {"base_commit": entry.base_commit, "changed_paths": changed, "patch": entry.patch}
        arms = {"A": [c["id"] for c in candidates]}
        try:
            voters = [verify_candidate_set(runtime / f"voter-{n}", source, knowledge, context, candidates) for n in (1, 2, 3)] if candidates else []
            arms = aggregate(arms["A"], voters)
            result["paired"] = True
        except Exception as exc:
            logger.exception("Verification failed for %s", entry.instance_id)
            result["errors"].append({"stage": "verification", "type": type(exc).__name__, "reason": str(exc)})
        result["arms"] = arms
        try:
            verdicts = judge_once(entry, candidates, runtime / "judge")
            result["scores"] = score_subsets(entry, candidates, arms, verdicts)
            result["baseline_scored"] = True
        except Exception as exc:
            logger.exception("Scoring failed for %s", entry.instance_id)
            result["errors"].append({"stage": "judge", "type": type(exc).__name__, "reason": str(exc)})
        result["operational_success"] = result["paired"] and result["baseline_scored"]
    except Exception as exc:
        logger.exception("Baseline/preparation failed for %s", entry.instance_id)
        result["errors"].append({"stage": "baseline", "type": type(exc).__name__, "reason": str(exc)})
    finally:
        result["wall_seconds"] = time.monotonic() - start
        save(output / "result.json", result)
        export_artifacts(runtime, output)
    return result


def metrics(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    scores = [r["scores"][arm] for r in rows]
    if not scores:
        return {"entries": 0, "micro": None, "macro": None}
    totals = {key: sum(s[key] for s in scores) for key in ("tp", "fp", "fn", "ignored", "generated", "expected")}
    p, r = precision_recall(totals["tp"], totals["generated"] - totals["ignored"], totals["expected"])
    precision_rows = [s for s in scores if s["generated"] > s["ignored"] or not s["expected"]]
    positive_rows = [s for s in scores if s["expected"]]
    return {
        "entries": len(scores),
        "counts": totals,
        "micro": {"precision": p, "recall": r, "f1": f1_score(p, r)},
        "macro": {
            "precision": sum(s["precision"] for s in precision_rows) / len(precision_rows) if precision_rows else 0.0,
            "recall": sum(s["recall"] for s in positive_rows) / len(positive_rows) if positive_rows else 1.0,
            "f1": sum(s["f1"] for s in scores) / len(scores),
        },
        "macro_denominators": {"precision": len(precision_rows), "recall": len(positive_rows), "f1": len(scores)},
    }


def summarize(selection: dict[str, Any], artifacts: Path) -> dict[str, Any]:
    found = {}
    for path in artifacts.rglob("result.json"):
        row = read(path)
        key = row["instance_id"]
        if key in found or key not in selection["selected"] or row["config"] != selection["config"]:
            raise ValueError("Duplicate, unexpected entry or configuration in artifacts")
        found[key] = row
    rows = list(found.values())
    paired = [r for r in rows if r["paired"] and r["baseline_scored"]]
    baseline = [r for r in rows if r["baseline_scored"]]
    complete = len(rows) == len(selection["selected"]) and all(r["operational_success"] for r in rows)
    exercised = complete and all(r["candidates"] > 0 for r in rows)
    costs: list[dict[str, Any]] = []
    for path in artifacts.rglob("metrics.json"):
        if path.parent.name == "baseline":
            value = read(path)
            costs.append({"path": str(path), "credits": value.get("ai_credits"), "tokens": value.get("total_tokens"), "complete": value.get("usage_complete", False)})
        elif path.parent.name == "judge" or path.parent.name.startswith("voter-"):
            costs.append({"path": str(path), **read(path)})
    missing_usage = [str(p.parent) for p in artifacts.rglob("started.json") if p.parent.name in {"baseline", "judge", "voter-1", "voter-2", "voter-3"} and not (p.parent / "metrics.json").exists()]
    stages = {"baseline": [], "verifier": [], "judge": []}
    partial_usage_errors = []
    for path in artifacts.rglob("_run-metrics.json"):
        if path.parent.name != "baseline" or (path.parent / "metrics.json").exists():
            continue
        try:
            value = read(path)
            costs.append({"path": str(path), "credits": value.get("ai_credits"), "tokens": value.get("total_tokens"), "complete": False, "partial": True})
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as exc:
            logger.warning("Unreadable interrupted usage artifact %s: %s", path, exc)
            partial_usage_errors.append(str(path))
    for path in artifacts.rglob("started.json"):
        stage = "verifier" if path.parent.name in {"voter-1", "voter-2", "voter-3"} else path.parent.name
        if stage in stages:
            stages[stage].append(path.parent)
    decisions = [{"path": str(path), "decisions": read(path)} for path in artifacts.rglob("decisions.json")]
    return {
        "selection": selection,
        "baseline_completed": sum(r["baseline_complete"] for r in rows),
        "baseline_scored": len(baseline),
        "paired": len(paired),
        "missing": [key for key in selection["selected"] if key not in found],
        "exclusions": [{"instance_id": r["instance_id"], "errors": r["errors"]} for r in rows if not r["operational_success"]],
        "baseline_all": metrics(baseline, "A"),
        "paired_arms": {arm: metrics(paired, arm) for arm in ("A", "B", "C")},
        "paired_change_from_A": {
            arm: {
                "tp_retained": sum(r["scores"][arm]["tp"] for r in paired),
                "tp_lost": sum(r["scores"]["A"]["tp"] - r["scores"][arm]["tp"] for r in paired),
                "fp_removed": sum(r["scores"]["A"]["fp"] - r["scores"][arm]["fp"] for r in paired),
            }
            for arm in ("B", "C")
        },
        "smoke_gate_passed": exercised if selection["phase"] == "smoke" else None,
        "operational_success": complete,
        "usage": costs,
        "usage_missing": missing_usage,
        "partial_usage_errors": partial_usage_errors,
        "invocations": {
            stage: {"started": len(paths), "usage_recorded": sum((path / "metrics.json").exists() for path in paths), "process_failures": sum((path / "failure.json").exists() for path in paths)}
            for stage, paths in stages.items()
        },
        "voter_decisions": decisions,
        "known_credits": sum(c["credits"] for c in costs if c.get("credits") is not None),
        "usage_complete": not missing_usage
        and len(rows) == len(selection["selected"])
        and all(c.get("credits") is not None and c.get("tokens") is not None and c.get("complete", True) for c in costs),
        "publication": "artifact-only; no leaderboard, Braintrust or Kusto",
    }
