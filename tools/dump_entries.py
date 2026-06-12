import contextlib
import json
import sys
from pathlib import Path

BASE = Path("evaluation_results/gh_run_27240290541")
DATASET = Path("dataset/codereview.jsonl")


def load_ood(iid: str) -> tuple[str, list[dict]]:
    hits = list(BASE.rglob(f"{iid}.jsonl"))
    if not hits:
        return "", []
    r = json.loads(hits[0].read_text(encoding="utf-8").strip().splitlines()[0])
    edom = (r.get("domain") or "").lower()
    findings: list = []
    with contextlib.suppress(Exception):
        findings = json.loads(r.get("output", "")).get("findings", [])
    ood = [x for x in findings if isinstance(x, dict) and (x.get("domain") or "").lower() not in ("", edom)]
    return edom, ood


def main() -> None:
    domain = sys.argv[1]
    nums = sys.argv[2:] if len(sys.argv) > 2 else None
    with DATASET.open(encoding="utf-8") as fh:
        rows = {x["instance_id"]: x for x in (json.loads(line) for line in fh if line.strip())}
    ids = sorted(k for k in rows if k.startswith(f"synthetic__{domain}-"))
    if nums:
        ids = [f"synthetic__{domain}-{n}" for n in nums]
    for iid in ids:
        e = rows[iid]
        edom, ood = load_ood(iid)
        print("\n" + "#" * 80)
        print(f"# {iid} domain={edom} exp={len(e['expected_comments'])} ood={len(ood)}")
        print("# EXPECTED:")
        for c in e["expected_comments"]:
            print(f"#   {c.get('file')}:{c.get('line_start')} [{c.get('domain')}/{c.get('severity')}] {c.get('body', '')[:90]}")
        print("# OOD:")
        for x in ood:
            fp = (x.get("filePath") or "?").split("/")[-1]
            print(f"#   {x.get('domain')}/{x.get('severity')} {fp}:{x.get('lineNumber')} | {' '.join(str(x.get('issue', '')).split())[:95]}")
        print("# PATCH:")
        print(e["patch"])


if __name__ == "__main__":
    main()
