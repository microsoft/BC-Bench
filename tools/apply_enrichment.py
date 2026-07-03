"""Apply enrichment designs to dataset/codereview.jsonl.

Reads tmp/enrichment-design-{security,privacy,style,upgrade}.json files.
For each entry:
  - Appends a new-file diff block to the entry's existing patch
  - Adds the designed expected_comments to entry.expected_comments

Writes the modified dataset back in place. Run probe afterwards to verify.

Usage:
    uv run python tools/apply_enrichment.py
    uv run python tools/apply_enrichment.py --domain security
    uv run python tools/apply_enrichment.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "dataset" / "codereview.jsonl"
DESIGN_DIR = REPO_ROOT / "tmp"
DOMAINS = ("security", "privacy", "style", "upgrade")


def build_new_file_diff(file_path: str, content: str) -> str:
    """Render a new-file unified diff block."""
    lines = content.split("\n")
    if lines and lines[-1] == "":
        # remove trailing empty (file ends with newline) — count actual content lines
        lines = lines[:-1]
    n = len(lines)
    diff = [
        f"diff --git a/{file_path} b/{file_path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{file_path}",
        f"@@ -0,0 +1,{n} @@",
    ]
    diff.extend(f"+{line}" for line in lines)
    return "\n".join(diff) + "\n"


def load_designs(domain: str) -> list[dict]:
    path = DESIGN_DIR / f"enrichment-design-{domain}.json"
    if not path.exists():
        raise FileNotFoundError(f"missing design file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def apply(domains: list[str], dry_run: bool = False) -> None:
    designs_by_iid: dict[str, dict] = {}
    for d in domains:
        for design in load_designs(d):
            iid = design["instance_id"]
            if iid in designs_by_iid:
                raise ValueError(f"duplicate design for {iid}")
            designs_by_iid[iid] = design

    print(f"Loaded {len(designs_by_iid)} designs from {len(domains)} domain(s)")

    out_lines: list[str] = []
    applied = 0
    with DATASET.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                out_lines.append(raw_line)
                continue
            entry = json.loads(line)
            iid = entry["instance_id"]
            if iid not in designs_by_iid:
                out_lines.append(raw_line)
                continue

            design = designs_by_iid[iid]
            existing_patch = entry.get("patch", "")
            new_file_diff = build_new_file_diff(design["new_file_path"], design["new_file_content"])
            if not existing_patch.endswith("\n"):
                existing_patch = existing_patch + "\n"
            entry["patch"] = existing_patch + new_file_diff

            expected = list(entry.get("expected_comments") or [])
            expected.extend(design["expected_comments"])
            entry["expected_comments"] = expected

            out_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
            applied += 1
            print(f"  [+] {iid} -> {design['new_file_path']} (+{len(design['expected_comments'])} expected)")

    if dry_run:
        print(f"\nDRY RUN: would apply {applied} enrichments; dataset NOT modified")
        return

    DATASET.write_text("".join(out_lines), encoding="utf-8")
    print(f"\nApplied {applied} enrichments. Dataset rewritten.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--domain", choices=DOMAINS, action="append", default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    domains = args.domain or list(DOMAINS)
    apply(domains, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
