"""Reformat pre-existing FP-bait files in dataset patches from 4-space to 2-space indent.

These trivial helper files use 4-space indent which the skill correctly flags as
style-domain violations, producing OOD findings on non-style entries. Converting
to 2-space matches the project style standard and eliminates the OOD source.

Only modifies the listed (instance_id, file) pairs and only the leading whitespace
on '+' lines within each matching diff block.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "dataset" / "codereview.jsonl"

# (instance_id, file_path) pairs whose pre-existing diff block needs unindenting
TARGETS = [
    ("synthetic__security-002", "src/SecureKeyManager.Codeunit.al"),
    ("synthetic__security-003", "src/SafeErrorHandler.Codeunit.al"),
    ("synthetic__security-004", "src/AppConstants.Codeunit.al"),
    ("synthetic__privacy-004", "src/SystemErrorHandler.Codeunit.al"),
    ("synthetic__privacy-004", "src/ErrorLogEntry.Table.al"),
    ("synthetic__privacy-008", "src/BusinessEntityRegistry.Table.al"),
    ("synthetic__privacy-009", "src/TaxDataMigrationHelper.Codeunit.al"),
    ("synthetic__upgrade-001", "src/CustomerCardCreditLimitExt.PageExt.al"),
    ("synthetic__upgrade-002", "src/EnumConversionHelper.Codeunit.al"),
    ("synthetic__upgrade-002", "src/PaymentMethodType.Enum.al"),
    ("synthetic__upgrade-003", "src/CustomerListEnhancements.PageExt.al"),
    ("synthetic__upgrade-003", "src/ModernAPIHelper.Codeunit.al"),
    ("synthetic__upgrade-004", "src/GenericUpgradeHandler.Codeunit.al"),
    ("synthetic__upgrade-004", "src/MigrationStatusTracker.Table.al"),
]


def unindent_plus_line(line: str) -> str:
    if not line.startswith("+"):
        return line
    payload = line[1:]
    # match leading 4-space runs, replace each with 2 spaces
    m = re.match(r"^( +)", payload)
    if not m:
        return line
    indent = m.group(1)
    if len(indent) % 4 != 0:
        return line  # not pure 4-space; leave alone
    new_indent = " " * (len(indent) // 2)
    return "+" + new_indent + payload[len(indent) :]


def reindent_file_block(patch: str, file_path: str) -> tuple[str, int]:
    """Reformat leading 4-space indent to 2-space on '+' lines inside the diff block for file_path."""
    marker = f"diff --git a/{file_path} b/{file_path}\n"
    start = patch.find(marker)
    if start == -1:
        return patch, 0
    # find end = next 'diff --git' or end of patch
    end = patch.find("\ndiff --git ", start + len(marker))
    if end == -1:
        block = patch[start:]
        tail = ""
    else:
        block = patch[start : end + 1]  # include leading \n of separator? no, end+1 is \n itself - take up to end+1
        # actually safer:
        block = patch[start:end] + "\n"  # ensure block ends with newline
        tail = patch[end + 1 :]  # skip the leading '\n' we put on block
    if end == -1:
        head = patch[:start]
        tail = ""
    else:
        head = patch[:start]

    lines = block.split("\n")
    new_lines = [unindent_plus_line(ln) for ln in lines]
    changes = sum(1 for a, b in zip(lines, new_lines, strict=True) if a != b)
    new_block = "\n".join(new_lines)
    return head + new_block + tail, changes


def main() -> None:
    by_iid: dict[str, list[str]] = {}
    for iid, fp in TARGETS:
        by_iid.setdefault(iid, []).append(fp)

    out_lines: list[str] = []
    total_changes = 0
    touched_entries = 0
    with DATASET.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                out_lines.append(raw_line)
                continue
            entry = json.loads(line)
            iid = entry["instance_id"]
            if iid not in by_iid:
                out_lines.append(raw_line)
                continue

            patch = entry["patch"]
            entry_changes = 0
            for fp in by_iid[iid]:
                patch, n = reindent_file_block(patch, fp)
                entry_changes += n
                if n == 0:
                    print(f"  ! {iid}: no changes for {fp} (block not found or already 2-space)")
                else:
                    print(f"  [+] {iid}: {fp} ({n} lines reindented)")
            entry["patch"] = patch
            out_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
            total_changes += entry_changes
            if entry_changes:
                touched_entries += 1

    DATASET.write_text("".join(out_lines), encoding="utf-8")
    print(f"\nReformatted {touched_entries} entries; {total_changes} lines reindented total.")


if __name__ == "__main__":
    main()
