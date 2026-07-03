"""Generate out-of-domain (OOD) worklist for a domain from the latest gh run artifacts."""

import contextlib
import json
import sys
from pathlib import Path

BASE = Path("evaluation_results/gh_run_27240290541")
VALID = {"security", "performance", "style", "accessibility", "upgrade", "privacy"}


def load_entry(iid: str) -> dict:
    hits = list(BASE.rglob(f"{iid}.jsonl"))
    if not hits:
        return {}
    text = hits[0].read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text.splitlines()[0])


def main() -> None:
    domain = sys.argv[1]
    ids = sorted({p.stem for p in BASE.rglob(f"synthetic__{domain}-*.jsonl")})
    print(f"{domain} entries: {len(ids)}")
    for iid in ids:
        r = load_entry(iid)
        if not r:
            print(iid, "NO_DATA")
            continue
        edom = (r.get("domain") or "").lower()
        findings: list = []
        with contextlib.suppress(Exception):
            findings = json.loads(r.get("output", "")).get("findings", [])
        ood = [f for f in findings if isinstance(f, dict) and (f.get("domain") or "").lower() not in ("", edom)]
        doms = sorted({(f.get("domain") or "").lower() for f in ood})
        exp = len(r.get("expected_comments", []))
        f1 = r.get("f1")
        print(f"{iid}  exp={exp} ood={len(ood)} f1={f1} oodDoms={doms}")


if __name__ == "__main__":
    main()
