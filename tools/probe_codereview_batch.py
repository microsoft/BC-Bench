"""Parallel batch runner for probe_codereview_case.py.

Spawns N concurrent probe subprocesses, one per instance_id. Writes one
report JSON per entry under tmp/cr-probe-reports/. Prints a final aggregate.

Usage:
    uv run python tools/probe_codereview_batch.py --all-zero --concurrency 4
    uv run python tools/probe_codereview_batch.py --domain security --concurrency 4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "dataset" / "codereview.jsonl"
REPORT_ROOT = REPO_ROOT / "tmp" / "cr-probe-reports"
PROBE = REPO_ROOT / "tools" / "probe_codereview_case.py"


def select_ids(only: list[str] | None, zero_only: bool, domain: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
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
            out.append((iid, ed))
    return out


def run_probe(iid: str, model: str) -> tuple[str, int, str]:
    log_path = REPORT_ROOT / f"{iid}.stdout.log"
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as out:
        proc = subprocess.run(
            ["uv", "run", "python", str(PROBE), iid, "--model", model],
            cwd=REPO_ROOT,
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    elapsed = time.time() - t0
    return (iid, proc.returncode, f"{elapsed:6.1f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*")
    p.add_argument("--all-zero", action="store_true")
    p.add_argument("--domain", default=None)
    p.add_argument("--model", default="claude-opus-4.8")
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args()

    targets = select_ids(only=args.ids or None, zero_only=args.all_zero, domain=args.domain)
    if not targets:
        print("no entries matched")
        return

    print(f"Probing {len(targets)} entries with model={args.model} concurrency={args.concurrency}", flush=True)
    for iid, dom in targets:
        print(f"  - {iid} ({dom})")
    print(flush=True)

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    done = 0
    failed: list[str] = []
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {ex.submit(run_probe, iid, args.model): iid for iid, _ in targets}
        for fut in as_completed(futures):
            iid, rc, elapsed = fut.result()
            done += 1
            tag = "OK" if rc == 0 else f"ERR rc={rc}"
            print(f"[{done}/{len(targets)}] {iid:35} {elapsed} {tag}", flush=True)
            if rc != 0:
                failed.append(iid)
    total = time.time() - t_start
    print(f"\nBatch done in {total / 60:.1f} min. {len(failed)} failures.", flush=True)
    if failed:
        for iid in failed:
            print(f"  FAIL {iid}  see tmp/cr-probe-reports/{iid}.stdout.log", flush=True)

    print("\n===== AGGREGATE =====")
    for iid, _dom in targets:
        rp = REPORT_ROOT / f"{iid}.json"
        if not rp.exists():
            print(f"  ?    {iid:35} (no report)")
            continue
        try:
            r = json.loads(rp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  ERR  {iid:35} (invalid report)")
            continue
        if "error" in r:
            print(f"  ERR  {iid:35} {r['error']}")
        else:
            n_in = len(r["in_domain_findings"]) if isinstance(r["in_domain_findings"], list) else r["in_domain_findings"]
            tag = "OK  " if (not r["missed"] and not r["ood"]) else "FAIL"
            print(f"  {tag} {iid:35} expected={r['expected']} matched={r['matched']} missed={len(r['missed'])} ood={len(r['ood'])} in_domain={n_in}")


if __name__ == "__main__":
    main()
