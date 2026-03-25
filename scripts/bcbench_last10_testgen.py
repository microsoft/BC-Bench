#!/usr/bin/env python3
"""bcbench_last10_testgen.py

BC-Bench: download GitHub Actions artifact ZIPs for the last N workflow runs and do quick failure analysis.

Why this exists
- In the BC-Bench workflow, evaluation results are uploaded as ZIP artifacts that contain one or more .jsonl files.
- The internal manual review command typically used is:
    uv run bcbench result review <path-to-jsonl> -c "test-generation"
  (see internal notes/ppt referenced in your org).

This script helps you:
1) Download the *artifact ZIPs* from GitHub Actions runs (or use already-downloaded ZIPs).
2) Extract them safely.
3) Collect .jsonl/.txt files.
4) Aggregate pass/fail per instance_id and export CSVs.
5) Extract the generated code + error messages for top failing instances.

Modes
A) Download mode (from GitHub Actions):
   python bcbench_last10_testgen.py download --branch <your-branch>

B) Local mode (ZIPs already on disk):
   python bcbench_last10_testgen.py local --input <zip-or-folder>

Outputs (in --out folder)
- runs_used.json
- artifacts/run-<run_id>/...         (downloaded ZIPs + extracted contents)
- files/run-<run_id>/...             (collected .jsonl/.txt copies)
- summary.csv
- top_failures.csv
- extracted_tests/<instance_id>/*

Auth (download mode)
- Set environment variable GITHUB_TOKEN with permissions to read Actions artifacts.

"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except Exception as e:  # pragma: no cover
    requests = None


# ----------------------------
# Generic helpers
# ----------------------------

def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", (s or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s or "artifact"


def is_zip_path(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() == ".zip"


def list_zip_inputs(input_path: Path) -> List[Path]:
    """Return ZIP(s) from a file or a directory, sorted by mtime desc."""
    if input_path.is_file():
        if not is_zip_path(input_path):
            die(f"--input is a file but not a .zip: {input_path}")
        return [input_path]
    if input_path.is_dir():
        zips = [p for p in input_path.rglob("*.zip") if p.is_file()]
        if not zips:
            die(f"No .zip files found under: {input_path}")
        zips.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return zips
    die(f"--input path not found: {input_path}")


def safe_extract_zipfile(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extract a ZipFile safely (zip-slip protection)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    for member in zf.infolist():
        name = member.filename
        if not name or name.endswith("/") or member.is_dir():
            continue
        target = (dest_dir / name).resolve()
        if not str(target).startswith(str(dest_root)):
            die(f"Unsafe path in zip: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)


def safe_extract_zip_path(zip_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        safe_extract_zipfile(zf, dest_dir)


def safe_extract_zip_bytes(zip_bytes: bytes, dest_dir: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        safe_extract_zipfile(zf, dest_dir)


def rglob_files(root: Path, pattern: str) -> List[Path]:
    return [p for p in root.rglob(pattern) if p.is_file()]


# ----------------------------
# GitHub API helpers (download mode)
# ----------------------------

def expand_nested_zips(root: Path, max_depth: int = 2) -> int:
    """Recursively extract any nested .zip files found under root.

    Why: GitHub Actions 'artifact' is a ZIP, and sometimes the artifact payload contains ZIP(s)
    (e.g., per-test-case zips). Without recursive extraction, .jsonl files inside nested ZIPs
    won't be discovered by the collector.

    Returns: number of nested zip files extracted.
    """
    extracted_count = 0
    if max_depth <= 0:
        return 0

    # Breadth-first by depth to avoid deep recursion issues
    current_roots = [root]
    for depth in range(1, max_depth + 1):
        next_roots = []
        for r in current_roots:
            for zp in r.rglob('*.zip'):
                if not zp.is_file():
                    continue
                # Skip zips we already expanded (heuristic: _extracted folder exists)
                out_dir = zp.with_suffix('')
                out_dir = out_dir.parent / (out_dir.name + '_extracted')
                if out_dir.exists():
                    continue
                try:
                    safe_extract_zip_path(zp, out_dir)
                    extracted_count += 1
                    next_roots.append(out_dir)
                except zipfile.BadZipFile:
                    # Not a valid zip; ignore
                    continue
        current_roots = next_roots
        if not current_roots:
            break

    return extracted_count


def require_requests() -> None:
    if requests is None:
        die("Python package 'requests' is required for download mode. Install it with: pip install requests")


def gh_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bcbench-lastN-testgen",
    }


def get_json(session: "requests.Session", url: str, token: str, params: Optional[dict] = None) -> Dict[str, Any]:
    r = session.get(url, headers=gh_headers(token), params=params, timeout=60)
    if r.status_code >= 400:
        die(f"GitHub API error {r.status_code} for {url}\n{r.text[:1200]}")
    return r.json()


def get_bytes(session: "requests.Session", url: str, token: str) -> bytes:
    r = session.get(url, headers=gh_headers(token), timeout=180, allow_redirects=True)
    if r.status_code >= 400:
        die(f"Download error {r.status_code} for {url}\n{r.text[:1200]}")
    return r.content


def parse_repo(repo: str) -> Tuple[str, str]:
    if "/" not in repo:
        die("--repo must be owner/repo (e.g. microsoft/BC-Bench)")
    owner, name = repo.split("/", 1)
    return owner, name


def resolve_workflow_id(session: "requests.Session", token: str, api_base: str, owner: str, repo: str, workflow: str) -> int:
    """Resolve workflow id from id / yaml filename / workflow name."""
    if workflow.isdigit():
        return int(workflow)

    url = f"{api_base}/repos/{owner}/{repo}/actions/workflows"
    data = get_json(session, url, token, params={"per_page": 100})
    workflows = data.get("workflows", [])

    # Match by YAML file name in path
    for w in workflows:
        p = w.get("path", "")
        if p.endswith("/" + workflow) or p == workflow:
            return int(w["id"])

    # Match by exact name (case-insensitive)
    target = workflow.strip().lower()
    for w in workflows:
        if w.get("name", "").strip().lower() == target:
            return int(w["id"])

    # Fuzzy fallback
    for w in workflows:
        if target in (w.get("name", "").lower()) or target in (w.get("path", "").lower()):
            return int(w["id"])

    die(f"Could not resolve workflow '{workflow}'. Try using workflow ID.")


def get_last_completed_runs(
    session: "requests.Session",
    token: str,
    api_base: str,
    owner: str,
    repo: str,
    workflow_id: int,
    branch: Optional[str],
    n: int,
) -> List[Dict[str, Any]]:
    """Return last n COMPLETED runs (newest first)."""
    url = f"{api_base}/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
    page = 1
    out: List[Dict[str, Any]] = []

    while len(out) < n:
        params: Dict[str, Any] = {"per_page": 100, "page": page}
        if branch:
            params["branch"] = branch
        data = get_json(session, url, token, params=params)
        runs = data.get("workflow_runs", [])
        if not runs:
            break
        for r in runs:
            if r.get("status") == "completed":
                out.append(r)
                if len(out) >= n:
                    break
        page += 1

    return out[:n]


def list_artifacts(session: "requests.Session", token: str, api_base: str, owner: str, repo: str, run_id: int) -> List[Dict[str, Any]]:
    url = f"{api_base}/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    data = get_json(session, url, token, params={"per_page": 100})
    return data.get("artifacts", []) or []


# ----------------------------
# Record parsing (JSONL or KV text fallback)
# ----------------------------

def try_parse_jsonl_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{") and line.endswith("}"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    return None


def split_kv_records(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("instance_id "):
        parts = re.split(r"\n(?=instance_id\s)", text)
        return [p.strip() for p in parts if p.strip()]
    return [text]


def parse_kv_record(block: str) -> Dict[str, Any]:
    b = block.replace("\r\n", "\n").replace("\r", "\n")

    gen_patch = None
    m = re.search(r"\bgenerated_patch\s", b)
    if m:
        start = m.end()
        m2 = re.search(r"\nerror_message\s", b[start:])
        if m2:
            gen_patch = b[start : start + m2.start()]
            rest = b[start + m2.start() :]
            head = b[: m.start()]
        else:
            gen_patch = b[start:]
            rest = ""
            head = b[: m.start()]
    else:
        head = b
        rest = ""

    head_tokens = re.split(r"\s+", head.strip())
    data: Dict[str, Any] = {}
    i = 0
    wanted = {
        "instance_id",
        "project",
        "model",
        "agent_name",
        "category",
        "resolved",
        "build",
        "timeout",
    }

    while i < len(head_tokens) - 1:
        key = head_tokens[i]
        val = head_tokens[i + 1]
        if key in wanted:
            data[key] = val
            i += 2
        else:
            i += 1

    if gen_patch is not None:
        data["generated_patch"] = gen_patch.strip("\n")

    if rest:
        rm = re.search(r"\berror_message\s", rest)
        if rm:
            start = rm.end()
            stop = None
            for key2 in [
                " metrics ",
                " execution_time ",
                " llm_duration ",
                "\nmetrics ",
                "\nexecution_time ",
            ]:
                pos = rest.find(key2, start)
                if pos != -1:
                    stop = pos
                    break
            em = rest[start:].strip() if stop is None else rest[start:stop].strip()
            data["error_message"] = em

    for k in ["resolved", "build", "timeout"]:
        if k in data:
            v = str(data[k]).strip().lower()
            if v in ("true", "false"):
                data[k] = (v == "true")

    return data


def iter_records_from_file(path: Path) -> List[Dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    recs: List[Dict[str, Any]] = []

    json_hits = 0
    for line in content.splitlines():
        obj = try_parse_jsonl_line(line)
        if obj is not None:
            recs.append(obj)
            json_hits += 1
    if json_hits > 0:
        return recs

    for block in split_kv_records(content):
        recs.append(parse_kv_record(block))
    return recs


# ----------------------------
# Status + code extraction
# ----------------------------

def get_test_id(rec: Dict[str, Any]) -> str:
    if isinstance(rec.get("instance_id"), str) and rec["instance_id"].strip():
        return rec["instance_id"].strip()
    for k in ["test_name", "testName", "name", "id", "testId", "test_id", "title"]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "unknown_test"


def get_category(rec: Dict[str, Any]) -> Optional[str]:
    v = rec.get("category")
    return v.strip() if isinstance(v, str) and v.strip() else None


def get_success_fail(rec: Dict[str, Any]) -> Optional[str]:
    if any(isinstance(rec.get(k), bool) for k in ("resolved", "build", "timeout")):
        resolved = rec.get("resolved")
        build = rec.get("build")
        timeout = rec.get("timeout")
        if resolved is True and build is True and timeout is False:
            return "success"
        return "fail"

    if isinstance(rec.get("passed"), bool):
        return "success" if rec["passed"] else "fail"
    if isinstance(rec.get("success"), bool):
        return "success" if rec["success"] else "fail"

    for k in ["status", "result", "outcome", "conclusion"]:
        v = rec.get(k)
        if isinstance(v, str):
            vl = v.strip().lower()
            if vl in ["passed", "pass", "success", "ok"]:
                return "success"
            if vl in ["failed", "fail", "error", "timeout", "cancelled", "canceled"]:
                return "fail"
    return None


def extract_code_text(rec: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    if isinstance(rec.get("generated_patch"), str) and rec["generated_patch"].strip():
        return (".diff", rec["generated_patch"])

    for k in [
        "test_code",
        "testCode",
        "generated_code",
        "generatedCode",
        "code",
        "al",
        "al_code",
        "source",
    ]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            ext = ".al" if ("codeunit" in v.lower() or "procedure" in v.lower()) else ".txt"
            return (ext, v)
    return None


@dataclass
class Agg:
    total: int = 0
    success: int = 0
    fail: int = 0
    last_seen_run: Optional[str] = None
    last_fail_run: Optional[str] = None


# ----------------------------
# Shared pipeline steps
# ----------------------------

def collect_files_for_run(run_dir: Path, run_out: Path, zip_depth: int = 2) -> int:
    """Copy .jsonl/.txt from run_dir into run_out with collision handling."""
    # Expand nested ZIPs so .jsonl inside inner zips are discoverable
    expand_nested_zips(run_dir, max_depth=zip_depth)

    candidates = rglob_files(run_dir, "*.jsonl") + rglob_files(run_dir, "*.txt")
    if run_out.exists():
        shutil.rmtree(run_out)
    run_out.mkdir(parents=True, exist_ok=True)

    seen: Dict[str, int] = {}
    for p in candidates:
        base = p.name
        n = seen.get(base, 0)
        seen[base] = n + 1
        target = run_out / (base if n == 0 else f"{n}_{base}")
        target.write_bytes(p.read_bytes())

    return len(candidates)


def analyze_collected_files(out_root: Path, out_files: Path, category: str, top_n: int) -> None:
    category_filter = category.strip().lower()
    agg: Dict[str, Agg] = {}
    rec_cache: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}

    for run_folder in sorted(out_files.glob("run-*")):
        run_id = run_folder.name
        for f in list(run_folder.glob("*.jsonl")) + list(run_folder.glob("*.txt")):
            for rec in iter_records_from_file(f):
                cat = get_category(rec)
                if category_filter and (not cat or cat.strip().lower() != category_filter):
                    continue

                tid = get_test_id(rec)
                status = get_success_fail(rec)
                if status is None:
                    continue

                a = agg.setdefault(tid, Agg())
                a.total += 1
                a.last_seen_run = run_id
                if status == "success":
                    a.success += 1
                else:
                    a.fail += 1
                    a.last_fail_run = run_id
                rec_cache.setdefault(tid, []).append((run_id, rec))

    if not agg:
        die(
            f"No records found for category='{category}'. "
            f"Tip: open one of the collected files under {out_files} and check the exact 'category' field value."
        )

    summary_csv = out_root / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "test_id",
            "category",
            "total",
            "success",
            "fail",
            "fail_rate",
            "last_seen_run",
            "last_fail_run",
        ])
        for tid, a in sorted(agg.items(), key=lambda kv: (-kv[1].fail, kv[0].lower())):
            rate = (a.fail / a.total) if a.total else 0.0
            w.writerow([tid, category, a.total, a.success, a.fail, f"{rate:.4f}", a.last_seen_run, a.last_fail_run])

    top = sorted(agg.items(), key=lambda kv: (kv[1].fail, kv[1].total), reverse=True)[: top_n]
    top_csv = out_root / "top_failures.csv"
    with top_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "test_id", "fail", "total", "fail_rate", "last_fail_run"])
        for i, (tid, a) in enumerate(top, start=1):
            rate = (a.fail / a.total) if a.total else 0.0
            w.writerow([i, tid, a.fail, a.total, f"{rate:.4f}", a.last_fail_run])

    extract_root = out_root / "extracted_tests"
    extract_root.mkdir(parents=True, exist_ok=True)

    for tid, a in top:
        folder = extract_root / safe_name(tid)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)

        meta = {
            "test_id": tid,
            "category": category,
            "total": a.total,
            "success": a.success,
            "fail": a.fail,
            "last_seen_run": a.last_seen_run,
            "last_fail_run": a.last_fail_run,
        }
        (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        records = sorted(rec_cache.get(tid, []), key=lambda x: x[0], reverse=True)[:10]
        saved = 0
        for run_id, rec in records:
            code = extract_code_text(rec)
            if not code:
                continue
            ext, txt = code
            (folder / f"{run_id}{ext}").write_text(txt, encoding="utf-8")
            saved += 1
            em = rec.get("error_message")
            if isinstance(em, str) and em.strip():
                (folder / f"{run_id}_error.txt").write_text(em, encoding="utf-8")

        (folder / "extraction_report.json").write_text(
            json.dumps({"code_snippets_saved": saved}, indent=2),
            encoding="utf-8",
        )


    # ---- Error variations per test_id (for failed cases) ----
    # For each test_id, group distinct error_message strings and count them.
    errors_summary_csv = out_root / "errors_summary.csv"
    with errors_summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test_id", "error_rank", "count", "error_message"])

        for tid, a in sorted(agg.items(), key=lambda kv: (-kv[1].fail, kv[0].lower())):
            # Only meaningful when there are failures
            if a.fail <= 0:
                continue

            # Collect error messages from cached records for this test
            variants: Dict[str, int] = {}
            for run_id, rec in rec_cache.get(tid, []):
                em = rec.get("error_message")
                if not isinstance(em, str):
                    continue
                em_norm = "\n".join([ln.rstrip() for ln in em.strip().splitlines()]).strip()
                if not em_norm:
                    continue
                variants[em_norm] = variants.get(em_norm, 0) + 1

            if not variants:
                continue

            # write a per-test JSON with sorted variants
            variants_sorted = sorted(variants.items(), key=lambda kv: kv[1], reverse=True)
            per_test = {
                "test_id": tid,
                "total_failures": a.fail,
                "distinct_error_messages": len(variants_sorted),
                "variants": [
                    {"count": c, "error_message": msg}
                    for msg, c in variants_sorted
                ],
            }
            # Store next to extracted test folder if exists
            test_folder = (out_root / "extracted_tests" / safe_name(tid))
            if test_folder.exists():
                (test_folder / "error_variations.json").write_text(json.dumps(per_test, indent=2), encoding="utf-8")

            # Also add to global summary CSV (cap error message length)
            for rank, (msg, c) in enumerate(variants_sorted, start=1):
                # Excel-friendly truncation in CSV (full text is in per-test json)
                msg_csv = msg if len(msg) <= 3000 else (msg[:3000] + "…")
                w.writerow([tid, rank, c, msg_csv])

    print("\nDONE ✅")
    print(f"- Summary: {summary_csv}")
    print(f"- Top failures: {top_csv}")
    print(f"- Error variations: {errors_summary_csv}")
    print(f"- Extracted tests: {extract_root}")


# ----------------------------
# Commands
# ----------------------------

def cmd_local(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    out_root = Path(args.out).expanduser().resolve()

    out_artifacts = out_root / "artifacts"
    out_files = out_root / "files"
    out_root.mkdir(parents=True, exist_ok=True)
    out_artifacts.mkdir(parents=True, exist_ok=True)
    out_files.mkdir(parents=True, exist_ok=True)

    zips = list_zip_inputs(input_path)
    if args.artifact_name_contains:
        sub = args.artifact_name_contains.lower()
        zips = [z for z in zips if sub in z.name.lower()]
    if not zips:
        die("No ZIPs left after filtering.")

    zips = zips[: max(1, args.runs)]

    runs_used = []
    for idx, zip_path in enumerate(zips, start=1):
        run_id = f"{idx:03d}"
        run_dir = out_artifacts / f"run-{run_id}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        safe_extract_zip_path(zip_path, run_dir)

        run_out = out_files / f"run-{run_id}"
        files_collected = collect_files_for_run(run_dir, run_out, zip_depth=args.zip_depth)

        runs_used.append(
            {
                "run": f"run-{run_id}",
                "zip": str(zip_path),
                "zip_mtime": zip_path.stat().st_mtime,
                "extracted_to": str(run_dir),
                "collected_files_to": str(run_out),
                "files_collected": files_collected,
            }
        )

        print(f"[run-{run_id}] extracted '{zip_path.name}' -> {run_dir}")
        print(f"[run-{run_id}] collected {files_collected} .jsonl/.txt -> {run_out}")

    (out_root / "runs_used.json").write_text(json.dumps(runs_used, indent=2), encoding="utf-8")
    analyze_collected_files(out_root, out_files, args.category, args.top)


def cmd_download(args: argparse.Namespace) -> None:
    require_requests()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        die("Set GITHUB_TOKEN environment variable for download mode.")

    owner, repo = parse_repo(args.repo)
    out_root = Path(args.out).expanduser().resolve()

    out_artifacts = out_root / "artifacts"
    out_files = out_root / "files"
    out_root.mkdir(parents=True, exist_ok=True)
    out_artifacts.mkdir(parents=True, exist_ok=True)
    out_files.mkdir(parents=True, exist_ok=True)

    api_base = args.github_api.rstrip("/")

    session = requests.Session()

    workflow_id = resolve_workflow_id(session, token, api_base, owner, repo, args.workflow)
    runs = get_last_completed_runs(session, token, api_base, owner, repo, workflow_id, args.branch, args.runs)
    if not runs:
        die("No completed runs found. Check --workflow/--branch.")

    runs_used = []

    for r in runs:
        run_id = int(r.get("id"))
        run_dir = out_artifacts / f"run-{run_id}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        artifacts = list_artifacts(session, token, api_base, owner, repo, run_id)
        if args.artifact_name_contains:
            sub = args.artifact_name_contains.lower()
            artifacts = [a for a in artifacts if sub in (a.get("name", "").lower())]

        if not artifacts:
            print(f"[run {run_id}] No artifacts (after filtering) -> skip")
            continue

        downloaded = 0
        extracted = 0

        for a in artifacts:
            art_id = int(a["id"])
            art_name = safe_name(a.get("name", f"artifact-{art_id}"))
            zip_url = f"{api_base}/repos/{owner}/{repo}/actions/artifacts/{art_id}/zip"

            print(f"[run {run_id}] downloading artifact '{art_name}' ({art_id})")
            zip_bytes = get_bytes(session, zip_url, token)
            downloaded += 1

            zip_path = run_dir / f"{art_name}.zip"
            zip_path.write_bytes(zip_bytes)

            extracted_dir = run_dir / f"{art_name}_extracted"
            safe_extract_zip_bytes(zip_bytes, extracted_dir)
            extracted += 1

        run_out = out_files / f"run-{run_id}"
        files_collected = collect_files_for_run(run_dir, run_out, zip_depth=args.zip_depth)

        runs_used.append(
            {
                "id": run_id,
                "html_url": r.get("html_url"),
                "head_branch": r.get("head_branch"),
                "head_sha": r.get("head_sha"),
                "conclusion": r.get("conclusion"),
                "created_at": r.get("created_at"),
                "downloaded_artifacts": downloaded,
                "extracted_artifacts": extracted,
                "extracted_to": str(run_dir),
                "collected_files_to": str(run_out),
                "files_collected": files_collected,
            }
        )

        print(f"[run {run_id}] collected {files_collected} .jsonl/.txt -> {run_out}")

    if not runs_used:
        die("No runs produced any artifacts/files (check artifact filter).")

    (out_root / "runs_used.json").write_text(json.dumps(runs_used, indent=2), encoding="utf-8")

    if args.download_only:
        print(f"\nDONE ✅ (download-only)  Runs list -> {out_root / 'runs_used.json'}")
        return

    analyze_collected_files(out_root, out_files, args.category, args.top)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    # Download
    d = sub.add_parser("download", help="Download artifact ZIPs from GitHub Actions and analyze")
    d.add_argument("--repo", default="microsoft/BC-Bench", help="owner/repo (default: microsoft/BC-Bench)")
    d.add_argument("--workflow", default="copilot-generation.yml", help="workflow filename/name/id (default: copilot-generation.yml)")
    d.add_argument("--branch", default=None, help="branch to filter runs (optional)")
    d.add_argument("--runs", type=int, default=10, help="how many last COMPLETED runs to download/analyze")
    d.add_argument("--out", default="out", help="output root folder")
    d.add_argument("--artifact-name-contains", default=None, help="only artifacts whose name contains substring")
    d.add_argument("--category", default="test-generation", help="record filter by category")
    d.add_argument("--top", type=int, default=5, help="top failing tests to extract")
    d.add_argument("--github-api", default="https://api.github.com", help="GitHub API base URL")
    d.add_argument("--download-only", action="store_true", help="only download/extract/collect files; skip analysis")
    d.add_argument("--zip-depth", type=int, default=2, help="max nested zip extraction depth (default: 2)")
    d.set_defaults(func=cmd_download)

    # Local
    l = sub.add_parser("local", help="Use local ZIPs (already downloaded) and analyze")
    l.add_argument("--input", required=True, help="path to artifacts .zip OR folder containing .zip files")
    l.add_argument("--runs", type=int, default=10, help="how many last ZIPs to analyze (by modified time)")
    l.add_argument("--out", default="out", help="output root folder")
    l.add_argument("--artifact-name-contains", default=None, help="only ZIPs whose filename contains substring")
    l.add_argument("--category", default="test-generation", help="record filter by category")
    l.add_argument("--top", type=int, default=5, help="top failing tests to extract")
    l.add_argument("--zip-depth", type=int, default=2, help="max nested zip extraction depth (default: 2)")
    l.set_defaults(func=cmd_local)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
