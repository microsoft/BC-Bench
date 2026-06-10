"""Generate out-of-domain (OOD) worklist for a domain from the latest gh run artifacts."""

import glob
import json
import os
import sys

BASE = "evaluation_results/gh_run_27240290541"
VALID = {"security", "performance", "style", "accessibility", "upgrade", "privacy"}


def load_entry(iid: str) -> dict:
    hits = glob.glob(os.path.join(BASE, "**", f"{iid}.jsonl"), recursive=True)
    if not hits:
        return {}
    text = open(hits[0], encoding="utf-8").read().strip()
    if not text:
        return {}
    return json.loads(text.splitlines()[0])


def main() -> None:
    domain = sys.argv[1]
    ids = sorted(
        {
            os.path.basename(p).replace(".jsonl", "")
            for p in glob.glob(os.path.join(BASE, "**", f"synthetic__{domain}-*.jsonl"), recursive=True)
        }
    )
    print(f"{domain} entries: {len(ids)}")
    for iid in ids:
        r = load_entry(iid)
        if not r:
            print(iid, "NO_DATA")
            continue
        edom = (r.get("domain") or "").lower()
        try:
            findings = json.loads(r.get("output", "")).get("findings", [])
        except Exception:
            findings = []
        ood = [f for f in findings if isinstance(f, dict) and (f.get("domain") or "").lower() not in ("", edom)]
        doms = sorted({(f.get("domain") or "").lower() for f in ood})
        exp = len(r.get("expected_comments", []))
        f1 = r.get("f1")
        print(f"{iid}  exp={exp} ood={len(ood)} f1={f1} oodDoms={doms}")


if __name__ == "__main__":
    main()
