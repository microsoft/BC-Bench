"""LLM-assisted CONTENT audit of code-review gold comments.

For each entry, a strong model reads the patch (code under review) and every gold
comment, then flags suspicious gold: issue not actually present, wrong line, duplicate,
severity mismatch, or debatable. It ONLY flags for human review — it never edits gold.

The gold body intentionally ends with "— See agent comment for details" (abbreviated
by design); the model is told to ignore that suffix.

Outputs (under --report-dir, default evaluation_results/gold-audit):
  - results.json : raw per-entry verdicts (written incrementally)
  - triage.md    : human-review checklist of flagged gold, with code context

Usage:
  uv run python tools/code-review/audit_gold_content.py --instance performance-005
  uv run python tools/code-review/audit_gold_content.py --pilot
  uv run python tools/code-review/audit_gold_content.py            # all 81
  uv run python tools/code-review/audit_gold_content.py --model claude-opus-4.8
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
DATASET = Path("dataset/codereview.jsonl")
AUDIT_FILE = "gold_audit.json"

PILOT_IDS = [
    "synthetic__security-001",
    "synthetic__security-009",
    "synthetic__performance-005",
    "synthetic__performance-007",
    "synthetic__privacy-001",
    "synthetic__privacy-012",
    "synthetic__style-002",
    "synthetic__upgrade-006",
]

_PROMPT = (
    "You are auditing the GOLD answer key of a code-review benchmark. In this directory "
    "read review_patch.diff (the code under review) and gold_comments.json (the expected "
    "review comments). For EACH gold comment decide whether it correctly identifies a REAL "
    "issue that is actually present in the patched code at the cited file and line. "
    "The body intentionally ends with '- See agent comment for details'; ignore that suffix. "
    "Judge the issue itself, not the wording: if the underlying concern is real and present at "
    "that line, mark it ok even if the body describes the mechanism imprecisely. "
    "Flag a comment as suspicious only if: the described issue is not actually present (not-present), "
    "the cited line does not match where the issue is (wrong-line), it duplicates another gold "
    "comment in the SAME file at the SAME line (duplicate), the severity is clearly wrong "
    "(severity-mismatch), or the issue is arguable/subjective (debatable). "
    "Write ONLY a JSON file at {audit} with this exact shape: "
    '[{{"index": 1, "verdict": "ok"|"suspicious", "category": "none"|"not-present"|"wrong-line"'
    '|"duplicate"|"severity-mismatch"|"debatable", "reason": "one short sentence"}}]. '
    "Include an entry for every gold comment. Respond with ONLY the JSON file, no other output."
)


def _find_copilot() -> str | None:
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def _load_entries(instance: str | None, pilot: bool) -> list[dict]:
    entries = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if pilot:
        return [e for e in entries if e["instance_id"] in PILOT_IDS]
    if instance:
        return [e for e in entries if instance in e["instance_id"]]
    return entries


def _new_file_lines(patch: str) -> dict[str, dict[int, str]]:
    files: dict[str, dict[int, str]] = {}
    cur: dict[int, str] | None = None
    n = 0
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = re.sub(r"^[ab]/", "", line[4:].strip())
            cur = files.setdefault(path, {}) if path != "/dev/null" else None
            continue
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if match:
            n = int(match.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            cur[n] = line[1:]
            n += 1
        elif line.startswith("-"):
            continue
        else:
            cur[n] = line[1:] if line[:1] == " " else line
            n += 1
    return files


def _code_context(files: dict[str, dict[int, str]], file: str, line: int, radius: int = 2) -> str:
    path = re.sub(r"^[ab]/", "", file)
    lines = files.get(path, {})
    out = []
    for k in range(line - radius, line + radius + 1):
        if k in lines:
            mark = ">>" if k == line else "  "
            out.append(f"{mark}{k:>4}| {lines[k]}")
    return "\n".join(out) if out else "(line not found in patch)"


def _audit_entry(entry: dict, copilot_cmd: str, model: str, timeout: int) -> list[dict]:
    gold = [
        {
            "index": i,
            "file": c["file"],
            "line_start": c["line_start"],
            "line_end": c.get("line_end"),
            "severity": c.get("severity"),
            "body": c["body"],
        }
        for i, c in enumerate(entry["expected_comments"], 1)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "review_patch.diff").write_text(entry["patch"], encoding="utf-8")
        (work / "gold_comments.json").write_text(json.dumps(gold, indent=2), encoding="utf-8")
        prompt = _PROMPT.format(audit=AUDIT_FILE)
        try:
            subprocess.run(
                [
                    copilot_cmd,
                    "--allow-all-tools",
                    "--disable-builtin-mcps",
                    "--no-custom-instructions",
                    f"--model={model}",
                    f"--prompt={prompt}",
                ],
                cwd=str(work),
                capture_output=True,
                timeout=timeout,
                check=True,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
            console.print(f"[red]{entry['instance_id']}: audit call failed ({type(exc).__name__})[/]")
            return []
        result_path = work / AUDIT_FILE
        if not result_path.exists():
            console.print(f"[red]{entry['instance_id']}: model wrote no audit file[/]")
            return []
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            console.print(f"[red]{entry['instance_id']}: unparseable audit file[/]")
            return []
    return raw if isinstance(raw, list) else []


def _enrich(entry: dict, verdicts: list[dict]) -> list[dict]:
    gold = entry["expected_comments"]
    files = _new_file_lines(entry["patch"])
    flagged = []
    for v in verdicts:
        if not isinstance(v, dict) or v.get("verdict") != "suspicious":
            continue
        idx = v.get("index", 0)
        c = gold[idx - 1] if 1 <= idx <= len(gold) else {}
        file = c.get("file", "?")
        line = c.get("line_start", 0)
        flagged.append(
            {
                "instance_id": entry["instance_id"],
                "index": idx,
                "file": file,
                "line_start": line,
                "line_end": c.get("line_end"),
                "severity": c.get("severity"),
                "category": v.get("category", "?"),
                "reason": v.get("reason", ""),
                "gold_body": c.get("body", ""),
                "code_context": _code_context(files, file, line),
            }
        )
    return flagged


def _render_console(entry: dict, flagged: list[dict]) -> None:
    gold = entry["expected_comments"]
    if not flagged:
        console.print(f"[green]{entry['instance_id']}: {len(gold)} gold, none flagged[/]")
        return
    table = Table(title=f"{entry['instance_id']} — {len(flagged)}/{len(gold)} flagged")
    table.add_column("#", justify="right")
    table.add_column("Location")
    table.add_column("Sev")
    table.add_column("Category")
    table.add_column("Reason")
    for f in flagged:
        table.add_row(
            str(f["index"]),
            f"{f['file']}:{f['line_start']}",
            str(f["severity"]),
            str(f["category"]),
            str(f["reason"]),
        )
    console.print(table)


def _write_triage_md(path: Path, flagged: list[dict], model: str, entries_audited: int, total_gold: int) -> None:
    by_cat: dict[str, int] = {}
    for f in flagged:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    lines = [
        "# Gold content audit — triage for review",
        "",
        f"- Model: `{model}`",
        f"- Entries audited: {entries_audited} | gold comments: {total_gold} | flagged: {len(flagged)}",
        "- These are MODEL SUGGESTIONS only. Verify each against the code before changing gold.",
        "",
        "## Summary by category",
        "",
        "| Category | Count |",
        "| --- | --- |",
    ]
    for cat, count in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {count} |")
    lines += ["", "## Flagged gold comments", ""]
    for f in sorted(flagged, key=lambda x: (x["instance_id"], x["index"])):
        end = f"-{f['line_end']}" if f.get("line_end") else ""
        body = f["gold_body"].split(" — See agent comment")[0]
        lines += [
            f"### {f['instance_id']} #{f['index']} — `{f['category']}`",
            "",
            f"- Location: `{f['file']}:{f['line_start']}{end}`  | severity: `{f['severity']}`",
            f"- Model reason: {f['reason']}",
            f"- Gold body: {body}",
            "",
            "```al",
            f["code_context"],
            "```",
            "",
            "- [ ] Verdict: keep / fix-wording / re-locate / remove  (decision: ____)",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", help="Audit instances whose id contains this substring.")
    parser.add_argument("--pilot", action="store_true", help="Audit the 8 pilot entries.")
    parser.add_argument("--model", default="claude-opus-4.8", help="Strong model for the audit.")
    parser.add_argument("--timeout", type=int, default=300, help="Per-entry timeout in seconds.")
    parser.add_argument("--report-dir", type=Path, default=Path("evaluation_results/gold-audit"))
    args = parser.parse_args()

    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        console.print("[red]copilot CLI not found on PATH.[/]")
        return

    entries = _load_entries(args.instance, args.pilot)
    if not entries:
        console.print("[red]No matching entries.[/]")
        return

    args.report_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.report_dir / "results.json"
    triage_path = args.report_dir / "triage.md"

    console.print(f"Auditing {len(entries)} entries with [cyan]{args.model}[/] -> {args.report_dir}\n")
    raw_results: list[dict] = []
    all_flagged: list[dict] = []
    total_gold = 0
    for n, entry in enumerate(entries, 1):
        total_gold += len(entry["expected_comments"])
        verdicts = _audit_entry(entry, copilot_cmd, args.model, args.timeout)
        flagged = _enrich(entry, verdicts)
        _render_console(entry, flagged)
        raw_results.append({"instance_id": entry["instance_id"], "verdicts": verdicts})
        all_flagged.extend(flagged)
        results_path.write_text(json.dumps(raw_results, indent=2), encoding="utf-8")
        _write_triage_md(triage_path, all_flagged, args.model, n, total_gold)

    console.print(
        f"\nDone. Flagged [yellow]{len(all_flagged)}[/] gold for review across {len(entries)} entries."
        f"\nTriage: {triage_path}\nRaw: {results_path}\n(no gold was edited)"
    )


if __name__ == "__main__":
    main()
