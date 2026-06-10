"""Run a single code-review entry locally and print a compact result summary.

Usage: uv run python tools/run_entry.py <instance_id>
Prints: metrics line + each generated finding's domain/severity/file:line + short issue.
Designed for the iterate-until-clean workflow.
"""

import json
import pathlib
import subprocess
import sys
import datetime

REPO = r"C:\repos\evals\BCApps"


def main() -> None:
    iid = sys.argv[1]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = pathlib.Path(f"evaluation_results/iter/{iid}_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "uv", "run", "bcbench", "-v", "evaluate", "copilot", iid,
        "--category", "code-review", "--model", "claude-opus-4.7",
        "--repo-path", REPO, "--output-dir", str(out_dir),
        "--run-id", f"run_{stamp}", "--al-mcp",
    ]
    subprocess.run(cmd, check=False)

    result_files = list(out_dir.rglob(f"{iid}.jsonl"))
    if not result_files:
        print("NO_RESULT")
        return
    r = json.loads(result_files[0].read_text(encoding="utf-8"))
    edom = (r.get("domain") or "").strip().lower()

    try:
        findings = json.loads(r.get("output", "")).get("findings", [])
    except (json.JSONDecodeError, TypeError, AttributeError):
        findings = []

    print("=" * 70)
    print(f"ENTRY {iid}  domain={edom}")
    print(f"METRICS matched={r.get('matched_comment_count')} missed={r.get('missed_comment_count')} "
          f"incorrect={r.get('incorrect_comment_count')} precision={r.get('precision'):.3f} "
          f"recall={r.get('recall'):.3f} f1={r.get('f1'):.3f}")
    ood = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        d = (f.get("domain") or "").strip().lower()
        fp = (f.get("filePath") or "?").split("/")[-1]
        tag = "OOD" if (d and d != edom) else "in "
        line = f"  [{tag}] {d}/{f.get('severity')} {fp}:{f.get('lineNumber')}  {' '.join(str(f.get('issue', '')).split())[:90]}"
        print(line)
        if d and d != edom:
            ood.append(line)
    print(f"OOD_COUNT={len(ood)}")


if __name__ == "__main__":
    main()
