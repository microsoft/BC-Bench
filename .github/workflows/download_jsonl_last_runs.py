#!/usr/bin/env python3
"""
Download JSONL artifacts from the last N completed GitHub Actions workflow runs,
extract zips, and collect .jsonl files locally.

This is a local replacement for the GitHub Actions workflow:
download-jsonl-from-evaluation.yml, but supports last N runs (e.g. 10).

Auth:
  Set env var GITHUB_TOKEN with actions:read permission (and contents:read for private repos).

Example:
  python download_jsonl_last_runs.py \
    --repo microsoft/BC-Bench \
    --workflow evaluation.yml \
    --branch my-branch \
    --runs 10 \
    --out out

Optional analysis (top failing tests across last N runs):
  python download_jsonl_last_runs.py ... --analyze --top 5
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests

GITHUB_API = "https://api.github.com"


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bcbench-local-downloader",
    }


def get_json(session: requests.Session, url: str, token: str, params: dict = None) -> Dict[str, Any]:
    r = session.get(url, headers=headers(token), params=params, timeout=60)
    if r.status_code >= 400:
        die(f"GitHub API error {r.status_code} for {url}\n{r.text[:1200]}")
    return r.json()


def get_bytes(session: requests.Session, url: str, token: str) -> bytes:
    r = session.get(url, headers=headers(token), timeout=180, allow_redirects=True)
    if r.status_code >= 400:
        die(f"Download error {r.status_code} for {url}\n{r.text[:1200]}")
    return r.content


def parse_repo(repo: str) -> Tuple[str, str]:
    if "/" not in repo:
        die("--repo must be owner/repo (e.g. microsoft/BC-Bench)")
    return tuple(repo.split("/", 1))  # owner, repo


def resolve_workflow_id(session: requests.Session, token: str, owner: str, repo: str, workflow: str) -> int:
    # workflow can be ID or file name or workflow name
    if workflow.isdigit():
        return int(workflow)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows"
    data = get_json(session, url, token, params={"per_page": 100})
    workflows = data.get("workflows", [])

    # match by file path ending
    for w in workflows:
        p = w.get("path", "")
        if p.endswith("/" + workflow) or p == workflow:
            return int(w["id"])

    # match by exact name
    wl = workflow.strip().lower()
    for w in workflows:
        if w.get("name", "").strip().lower() == wl:
            return int(w["id"])

    # fuzzy
    for w in workflows:
        if wl in (w.get("name", "").lower()) or wl in (w.get("path", "").lower()):
            return int(w["id"])

    die(f"Could not resolve workflow '{workflow}'. Try passing workflow ID.")


def get_last_completed_runs(
    session: requests.Session,
    token: str,
    owner: str,
    repo: str,
    workflow_id: int,
    branch: Optional[str],
    n: int
) -> List[Dict[str, Any]]:
    """
    Returns last n COMPLETED runs (newest first).
    We must paginate because GitHub returns mixed queued/in_progress/completed.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
    page = 1
    out = []
    while len(out) < n:
        params = {"per_page": 100, "page": page}
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


def list_artifacts(session: requests.Session, token: str, owner: str, repo: str, run_id: int) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    data = get_json(session, url, token, params={"per_page": 100})
    return data.get("artifacts", []) or []


def extract_zip_to_dir(zip_bytes: bytes, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(dest_dir)


def find_files(root: Path, pattern: str) -> List[Path]:
    return [p for p in root.rglob(pattern) if p.is_file()]


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s or "artifact"


# ---------------- Optional analysis helpers ----------------

def iter_jsonl_records(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def pick_test_id(rec: Dict[str, Any]) -> str:
    for k in ["test_name", "testName", "name", "id", "testId", "test_id", "title", "case"]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    t = rec.get("test")
    if isinstance(t, dict):
        for k in ["name", "id", "title"]:
            v = t.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return "unknown_test"


def pick_status(rec: Dict[str, Any]) -> Optional[str]:
    if isinstance(rec.get("passed"), bool):
        return "passed" if rec["passed"] else "failed"
    if isinstance(rec.get("success"), bool):
        return "passed" if rec["success"] else "failed"
    for k in ["status", "result", "outcome", "conclusion"]:
        v = rec.get(k)
        if isinstance(v, str):
            vl = v.lower().strip()
            if vl in ["passed", "pass", "success", "ok"]:
                return "passed"
            if vl in ["failed", "fail", "error", "timeout", "cancelled", "canceled"]:
                return "failed"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/repo (e.g. microsoft/BC-Bench)")
    ap.add_argument("--workflow", required=True, help="workflow file name (e.g. evaluation.yml), name, or id")
    ap.add_argument("--branch", default=None, help="branch to filter runs")
    ap.add_argument("--runs", type=int, default=10, help="how many last COMPLETED runs to download")
    ap.add_argument("--out", default="out", help="output root folder")
    ap.add_argument("--artifact-name-contains", default=None, help="optional: only artifacts whose name contains this substring")
    ap.add_argument("--analyze", action="store_true", help="optional: produce top failing tests across downloaded JSONL")
    ap.add_argument("--top", type=int, default=5, help="top failing tests for analysis output")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        die("Set GITHUB_TOKEN environment variable.")

    owner, repo = parse_repo(args.repo)
    out_root = Path(args.out)
    out_artifacts = out_root / "artifacts"
    out_jsonl = out_root / "jsonl"
    out_artifacts.mkdir(parents=True, exist_ok=True)
    out_jsonl.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    workflow_id = resolve_workflow_id(session, token, owner, repo, args.workflow)
    runs = get_last_completed_runs(session, token, owner, repo, workflow_id, args.branch, args.runs)

    if not runs:
        die("No completed runs found (check workflow/branch).")

    runs_used = []
    for r in runs:
        runs_used.append({
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "conclusion": r.get("conclusion"),
            "html_url": r.get("html_url"),
            "head_branch": r.get("head_branch"),
            "head_sha": r.get("head_sha"),
            "display_title": r.get("display_title"),
        })

    (out_root / "runs_used.json").write_text(json.dumps(runs_used, indent=2), encoding="utf-8")

    print(f"Found {len(runs)} completed runs. Downloading artifacts...")

    for r in runs:
        run_id = int(r["id"])
        run_dir = out_artifacts / f"run-{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        artifacts = list_artifacts(session, token, owner, repo, run_id)
        if args.artifact_name_contains:
            sub = args.artifact_name_contains.lower()
            artifacts = [a for a in artifacts if sub in (a.get("name", "").lower())]

        if not artifacts:
            print(f"[run {run_id}] No artifacts - skipping")
            continue

        # download each artifact zip
        for a in artifacts:
            art_id = int(a["id"])
            art_name = safe_name(a.get("name", f"artifact-{art_id}"))
            zip_url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/artifacts/{art_id}/zip"

            print(f"[run {run_id}] downloading artifact: {art_name} ({art_id})")
            zip_bytes = get_bytes(session, zip_url, token)

            zip_path = run_dir / f"{art_name}.zip"
            zip_path.write_bytes(zip_bytes)

            extracted_dir = run_dir / f"{art_name}_extracted"
            extract_zip_to_dir(zip_bytes, extracted_dir)

        # collect jsonl into out/jsonl/run-<id>
        jsonl_out_dir = out_jsonl / f"run-{run_id}"
        jsonl_out_dir.mkdir(parents=True, exist_ok=True)

        jsonl_files = find_files(run_dir, "*.jsonl")
        if not jsonl_files:
            print(f"[run {run_id}] No .jsonl found under {run_dir}")
            continue

        # copy with collision handling
        seen = {}
        for p in jsonl_files:
            base = p.name
            if base in seen:
                seen[base] += 1
                target = jsonl_out_dir / f"{seen[base]}_{base}"
            else:
                seen[base] = 0
                target = jsonl_out_dir / base
            target.write_bytes(p.read_bytes())

        print(f"[run {run_id}] JSONL collected -> {jsonl_out_dir} ({len(jsonl_files)} files)")

    print("\nDONE ✅")
    print(f"- Runs used: {len(runs)} (see {out_root / 'runs_used.json'})")
    print(f"- Artifacts: {out_artifacts}")
    print(f"- JSONL:     {out_jsonl}")

    # Optional analysis: top failing tests across last N runs
    if args.analyze:
        print("\nAnalyzing JSONL for pass/fail stats...")
        stats = {}  # test_id -> {passed, failed, total}
        for run_folder in sorted(out_jsonl.glob("run-*")):
            for jsonl_path in run_folder.glob("*.jsonl"):
                for rec in iter_jsonl_records(jsonl_path):
                    tid = pick_test_id(rec)
                    st = pick_status(rec)
                    if not st:
                        continue
                    s = stats.setdefault(tid, {"passed": 0, "failed": 0, "total": 0})
                    s["total"] += 1
                    s[st] += 1

        if not stats:
            die("No pass/fail records detected in JSONL. Share one JSONL line so we can map schema.")

        # write summary
        summary_path = out_root / "summary.json"
        summary_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

        # top failing
        top = sorted(stats.items(), key=lambda kv: kv[1]["failed"], reverse=True)[: args.top]
        top_path = out_root / "top_failures.json"
        top_path.write_text(json.dumps(top, indent=2), encoding="utf-8")

        print(f"- Summary stats: {summary_path}")
        print(f"- Top failures:  {top_path}")


if __name__ == "__main__":
    main()
