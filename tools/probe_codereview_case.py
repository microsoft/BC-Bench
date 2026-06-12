"""Local probe for a single code-review dataset entry.

Materializes the entry's patch into a throwaway folder, runs `copilot` with the
al-code-review skill, parses review.json, and validates OOD discipline +
expected-comment recall.

Usage:
    uv run python tools/probe_codereview_case.py synthetic__security-001
    uv run python tools/probe_codereview_case.py --all-zero
    uv run python tools/probe_codereview_case.py --all-zero --domain security
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _force_remove(func: Callable[[str], Any], path: str, exc: BaseException) -> None:
    Path(path).chmod(stat.S_IWRITE)
    func(path)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "dataset" / "codereview.jsonl"
SKILLS_SRC = REPO_ROOT / "src" / "bcbench" / "agent" / "shared" / "instructions" / "microsoft-BCApps"
PROBE_ROOT = REPO_ROOT / "tmp" / "cr-probe"
REPORT_ROOT = REPO_ROOT / "tmp" / "cr-probe-reports"
DEFAULT_MODEL = "claude-opus-4.8"

PROMPT_TEMPLATE = """/al-code-review

Review ONLY the current working-tree AL file changes for this evaluation entry.
Use the working tree diff only (git diff HEAD), and focus on changed *.al files.
Do NOT review committed history or the HEAD commit, and do NOT compare commits (for example, do NOT use HEAD~1..HEAD or origin/main comparisons).

Save findings to a file named "review.json" in the repository root.
The file must contain valid JSON with a top-level object named findings.
Each finding must include: filePath, lineNumber, severity, issue, recommendation, domain, suggestedCode
Allowed severity values are: critical, high, medium, low.
If there are no findings, write an empty findings list.
"""


@dataclass
class Entry:
    instance_id: str
    domain: str
    patch: str
    expected_comments: list[dict]
    match_line_tolerance: int


def load_entries(only: list[str] | None = None, zero_only: bool = False, domain: str | None = None) -> list[Entry]:
    out: list[Entry] = []
    with DATASET.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            raw = json.loads(line)
            iid = raw["instance_id"]
            ed = raw["metadata"]["area"]
            if only and iid not in only:
                continue
            if domain and ed != domain:
                continue
            if zero_only and raw["expected_comments"]:
                continue
            out.append(
                Entry(
                    instance_id=iid,
                    domain=ed,
                    patch=raw["patch"],
                    expected_comments=raw["expected_comments"],
                    match_line_tolerance=raw.get("match_line_tolerance", 2),
                )
            )
    return out


def materialize_patch(repo_path: Path, patch: str) -> list[str]:
    """Write '+' lines from a new-file diff into repo_path. Returns list of paths."""
    materialized: list[str] = []
    current_path: Path | None = None
    current_content: list[str] = []

    def flush() -> None:
        nonlocal current_path, current_content
        if current_path is None:
            return
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text("\n".join(current_content) + "\n", encoding="utf-8")
        materialized.append(current_path.relative_to(repo_path).as_posix())
        current_path = None
        current_content = []

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            flush()
            continue
        if line.startswith(("--- ", "new file mode", "index ")):
            continue
        if line.startswith("+++ "):
            rel = re.sub(r"^[ab]/", "", line[4:].strip())
            current_path = repo_path / rel
            current_content = []
            continue
        if line.startswith("@@"):
            continue
        if current_path is None:
            continue
        if line.startswith(("+", " ")):
            current_content.append(line[1:])
    flush()
    return materialized


def setup_workspace(entry: Entry) -> Path:
    repo_path = PROBE_ROOT / entry.instance_id
    if repo_path.exists():
        shutil.rmtree(repo_path, onexc=_force_remove)
    repo_path.mkdir(parents=True)

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "probe@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=repo_path, check=True)
    (repo_path / "README.md").write_text("probe scratch\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_path, check=True)

    github_dst = repo_path / ".github"
    shutil.copytree(SKILLS_SRC, github_dst)

    paths = materialize_patch(repo_path, entry.patch)
    if paths:
        subprocess.run(["git", "add", "-N", "--", *paths], cwd=repo_path, check=True)
    return repo_path


def run_copilot(repo_path: Path, model: str, log_dir: Path) -> subprocess.CompletedProcess:
    copilot = shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")
    if not copilot:
        raise RuntimeError("copilot CLI not in PATH")
    cmd = [
        copilot,
        "--allow-all-tools",
        "--disable-builtin-mcps",
        f"--model={model}",
        "--log-level=debug",
        f"--log-dir={log_dir.resolve()}",
        f"--prompt={PROMPT_TEMPLATE.replace(chr(10), ' ')}",
    ]
    return subprocess.run(cmd, cwd=repo_path, stderr=subprocess.PIPE, timeout=900, check=False)


def parse_findings(review_json_path: Path) -> list[dict] | None:
    if not review_json_path.exists():
        return None
    try:
        data = json.loads(review_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "findings" in data:
        return data["findings"]
    if isinstance(data, list):
        return data
    return None


def evaluate(entry: Entry, findings: list[dict]) -> dict:
    ood: list[dict] = []
    in_domain: list[dict] = []
    for f in findings:
        d = (f.get("domain") or "").strip().lower()
        if d and d != entry.domain.lower():
            ood.append(f)
        else:
            in_domain.append(f)

    matched: list[dict] = []
    missed: list[dict] = []
    for exp in entry.expected_comments:
        exp_file = exp["file"].lower()
        exp_lo = exp["line_start"] - entry.match_line_tolerance
        exp_hi = exp["line_end"] + entry.match_line_tolerance
        found = False
        for f in in_domain:
            fp = (f.get("filePath") or "").lower().replace("\\", "/")
            ln = f.get("lineNumber") or 0
            if exp_file in fp and exp_lo <= ln <= exp_hi:
                matched.append({"expected": exp, "finding": f})
                found = True
                break
        if not found:
            missed.append(exp)

    return {
        "entry": entry.instance_id,
        "domain": entry.domain,
        "expected": len(entry.expected_comments),
        "matched": len(matched),
        "missed": [{"file": m["file"], "line": m["line_start"], "issue": (m.get("body") or m.get("issue") or "")[:80]} for m in missed],
        "ood": [{"file": f.get("filePath"), "line": f.get("lineNumber"), "domain": f.get("domain"), "severity": f.get("severity"), "issue": (f.get("issue") or "")[:160]} for f in ood],
        "in_domain_findings": [
            {"file": f.get("filePath"), "line": f.get("lineNumber"), "severity": f.get("severity"), "issue": (f.get("issue") or "")[:200], "recommendation": (f.get("recommendation") or "")[:160]}
            for f in in_domain
        ],
        "total_findings": len(findings),
    }


def probe_one(entry: Entry, model: str, keep: bool = False) -> dict:
    print(f"  [setup] {entry.instance_id}", flush=True)
    repo_path = setup_workspace(entry)
    log_dir = repo_path / ".copilot-logs"
    log_dir.mkdir(exist_ok=True)
    print(f"  [run]   copilot {model} (cwd={repo_path})", flush=True)
    proc = run_copilot(repo_path, model, log_dir)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace")[-2000:])
        return {"entry": entry.instance_id, "error": f"copilot exit {proc.returncode}"}

    findings = parse_findings(repo_path / "review.json")
    if findings is None:
        return {"entry": entry.instance_id, "error": "no review.json or invalid JSON"}

    report = evaluate(entry, findings)
    if not keep:
        # leave repo for inspection if errors, else trim heavy logs
        for p in log_dir.glob("*.log"):
            with contextlib.suppress(OSError):
                p.unlink()
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*", help="instance_id(s) to probe")
    p.add_argument("--all-zero", action="store_true", help="probe all entries with empty expected_comments")
    p.add_argument("--domain", help="filter by domain (security/performance/style/upgrade/privacy)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--keep", action="store_true", help="don't delete log files after run")
    args = p.parse_args()

    entries = load_entries(only=args.ids or None, zero_only=args.all_zero, domain=args.domain)
    if not entries:
        print("no entries matched")
        return

    PROBE_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []
    for e in entries:
        print(f"\n== {e.instance_id} ({e.domain}) ==", flush=True)
        report = probe_one(e, args.model, keep=args.keep)
        report_path = REPORT_ROOT / f"{e.instance_id}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  [report] wrote {report_path.relative_to(REPO_ROOT)}", flush=True)
        summary.append(report)

    print("\n===== SUMMARY =====")
    for r in summary:
        if "error" in r:
            print(f"  ERR  {r['entry']}: {r['error']}")
        else:
            tag = "OK  " if (not r["missed"] and not r["ood"]) else "FAIL"
            print(f"  {tag} {r['entry']}: expected={r['expected']} matched={r['matched']} missed={len(r['missed'])} ood={len(r['ood'])}")


if __name__ == "__main__":
    main()
