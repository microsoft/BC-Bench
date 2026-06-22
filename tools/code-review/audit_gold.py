"""Intrinsic gold audit for code-review: validate each expected comment's location
against the patch it reviews. Pure/deterministic, no LLM, no run data.

Checks per gold comment:
  - file is actually present in the patch (normalized path)
  - line_start falls within a hunk's new-file line range for that file
  - whether the cited line is an ADDED ('+') line vs context

Usage:
  uv run python tools/code-review/audit_gold.py
  uv run python tools/code-review/audit_gold.py --instance upgrade-006
  uv run python tools/code-review/audit_gold.py --problems-only
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
DATASET = Path("dataset/codereview.jsonl")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _normalize_path(path: str) -> str:
    return re.sub(r"^[ab]/", "", path.strip()).replace("\\", "/")


@dataclass
class FileLines:
    added: set[int] = field(default_factory=set)
    context: set[int] = field(default_factory=set)

    @property
    def covered(self) -> set[int]:
        return self.added | self.context


def _parse_patch(patch: str) -> dict[str, FileLines]:
    files: dict[str, FileLines] = {}
    current: FileLines | None = None
    new_line = 0
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = _normalize_path(line[4:])
            if path == "/dev/null":
                current = None
                continue
            current = files.setdefault(path, FileLines())
            continue
        if line.startswith("--- "):
            continue
        match = HUNK_RE.match(line)
        if match:
            new_line = int(match.group(1))
            continue
        if current is None:
            continue
        if line.startswith("+"):
            current.added.add(new_line)
            new_line += 1
        elif line.startswith("-"):
            continue
        else:
            current.context.add(new_line)
            new_line += 1
    return files


@dataclass
class GoldFlag:
    instance_id: str
    index: int
    file: str
    line: int
    severity: str
    problem: str


def _audit_entry(data: dict) -> list[GoldFlag]:
    files = _parse_patch(data["patch"])
    patch_files = set(files)
    flags: list[GoldFlag] = []
    for i, c in enumerate(data["expected_comments"], 1):
        gold_file = _normalize_path(c["file"])
        line = c["line_start"]
        severity = c.get("severity", "?")
        if gold_file not in patch_files:
            close = [f for f in patch_files if Path(f).name == Path(gold_file).name]
            hint = f" (patch has {close[0]}?)" if close else ""
            flags.append(GoldFlag(data["instance_id"], i, gold_file, line, severity, f"file not in patch{hint}"))
            continue
        fl = files[gold_file]
        if line in fl.added:
            continue
        if line in fl.context:
            flags.append(GoldFlag(data["instance_id"], i, gold_file, line, severity, "line is context, not an added line"))
            continue
        covered = sorted(fl.covered)
        span = f"{covered[0]}-{covered[-1]}" if covered else "none"
        flags.append(GoldFlag(data["instance_id"], i, gold_file, line, severity, f"line outside patched range ({span})"))
    return flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", help="Only audit instances whose id contains this substring.")
    parser.add_argument("--problems-only", action="store_true", help="List only entries with flagged gold.")
    args = parser.parse_args()

    entries = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.instance:
        entries = [e for e in entries if args.instance in e["instance_id"]]

    all_flags: list[GoldFlag] = []
    total_gold = 0
    for entry in entries:
        total_gold += len(entry["expected_comments"])
        all_flags.extend(_audit_entry(entry))

    by_problem: dict[str, int] = {}
    for flag in all_flags:
        kind = flag.problem.split(" (")[0]
        by_problem[kind] = by_problem.get(kind, 0) + 1

    table = Table(title="Gold location problems")
    table.add_column("Instance")
    table.add_column("#", justify="right")
    table.add_column("Location")
    table.add_column("Sev")
    table.add_column("Problem")
    for flag in all_flags:
        table.add_row(flag.instance_id, str(flag.index), f"{flag.file}:{flag.line}", flag.severity, flag.problem)
    if all_flags:
        console.print(table)
    else:
        console.print("[green]No gold location problems found.[/]")

    console.print(
        f"\nEntries audited: {len(entries)} | gold comments: {total_gold} | "
        f"flagged: {len(all_flags)} ({len({f.instance_id for f in all_flags})} entries)"
    )
    for kind, count in sorted(by_problem.items(), key=lambda kv: -kv[1]):
        console.print(f"  - {kind}: {count}")


if __name__ == "__main__":
    main()
