#!/usr/bin/env python3

import csv
import sys
from collections import defaultdict
from pathlib import Path

# ----------------------------
# Configuration
# ----------------------------

ERROR_GROUPS = [
    "Generated tests Passed pre-patch",
    "Generated tests Failed post-patch",
    "Build or publish failed",
]

# ----------------------------
# Helpers
# ----------------------------

def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def extract_error_group(error_message: str) -> str:
    """
    Determine high-level error group based on the FIRST meaningful line.
    """
    if not error_message:
        return "Unknown"

    for raw_line in error_message.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        for group in ERROR_GROUPS:
            if line.startswith(group):
                return group

        # Fallback: first non-empty line
        return line

    return "Unknown"


# ----------------------------
# Core logic
# ----------------------------

def group_errors(errors_summary_csv: Path, out_dir: Path) -> Path:
    groups = {}

    with errors_summary_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            test_id = (row.get("test_id") or "").strip()
            error_message = row.get("error_message") or ""

            try:
                count = int(row.get("count", "1") or 1)
            except ValueError:
                count = 1

            error_group = extract_error_group(error_message)

            g = groups.setdefault(
                error_group,
                {
                    "occurrences": 0,
                    "tests": set(),
                    "full_messages": defaultdict(int),
                },
            )

            g["occurrences"] += count
            if test_id:
                g["tests"].add(test_id)
            if error_message.strip():
                g["full_messages"][error_message.strip()] += count

    if not groups:
        die("No data found in errors_summary.csv")

    # Prepare output rows
    out_rows = []
    for error_group, g in groups.items():
        top_message = ""
        if g["full_messages"]:
            top_message = max(
                g["full_messages"].items(),
                key=lambda kv: kv[1],
            )[0]

        out_rows.append(
            {
                "error_group": error_group,
                "occurrences": g["occurrences"],
                "distinct_tests": len(g["tests"]),
                "example_test_ids": ",".join(sorted(g["tests"])[:5]),
                "top_full_error_message": top_message,
            }
        )

    out_rows.sort(key=lambda r: r["occurrences"], reverse=True)

    out_csv = out_dir / "grouped_errors_summary.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "error_group",
                "occurrences",
                "distinct_tests",
                "example_test_ids",
                "top_full_error_message",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    return out_csv


# ----------------------------
# Entry point
# ----------------------------

def main() -> None:
    if len(sys.argv) != 3:
        die("Usage: python group_errors_from_summary.py <errors_summary.csv> <out_dir>")

    errors_summary_csv = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])

    if not errors_summary_csv.exists():
        die(f"File not found: {errors_summary_csv}")

    out_dir.mkdir(parents=True, exist_ok=True)

    out_csv = group_errors(errors_summary_csv, out_dir)
    print(f"✅ Grouped errors summary written to: {out_csv}")


if __name__ == "__main__":
    main()
