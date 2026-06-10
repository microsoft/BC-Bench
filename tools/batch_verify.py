"""Run several entries and print a one-line OOD summary per entry."""

import datetime
import json
import pathlib
import subprocess
import sys

REPO = r"C:\repos\evals\BCApps"


def run_one(iid: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = pathlib.Path(f"evaluation_results/iter/{iid}_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "uv", "run", "bcbench", "evaluate", "copilot", iid,
        "--category", "code-review", "--model", "claude-opus-4.7",
        "--repo-path", REPO, "--output-dir", str(out_dir),
        "--run-id", f"run_{stamp}", "--al-mcp",
    ]
    subprocess.run(cmd, check=False, capture_output=True)
    hits = list(out_dir.rglob(f"{iid}.jsonl"))
    if not hits:
        return f"{iid}: NO_RESULT"
    r = json.loads(hits[0].read_text(encoding="utf-8"))
    edom = (r.get("domain") or "").strip().lower()
    try:
        findings = json.loads(r.get("output", "")).get("findings", [])
    except Exception:
        findings = []
    ood = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        d = (f.get("domain") or "").strip().lower()
        if d and d != edom:
            fp = (f.get("filePath") or "?").split("/")[-1]
            ood.append(f"{d}/{f.get('severity')} {fp}:{f.get('lineNumber')} {' '.join(str(f.get('issue','')).split())[:70]}")
    line = (f"{iid}: f1={r.get('f1'):.3f} matched={r.get('matched_comment_count')} "
            f"missed={r.get('missed_comment_count')} incorrect={r.get('incorrect_comment_count')} OOD={len(ood)}")
    for o in ood:
        line += f"\n    [OOD] {o}"
    return line


def main() -> None:
    for iid in sys.argv[1:]:
        print(run_one(iid), flush=True)


if __name__ == "__main__":
    main()
