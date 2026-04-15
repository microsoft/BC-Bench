#!/usr/bin/env python3
"""
bcbench_analyze_artifacts.py

Analyze BC-Bench GitHub Actions artifacts that you already downloaded.

Supports TWO input modes (no GitHub API, no tokens), which can be COMBINED:

1) ZIP mode: point to a folder of artifact .zip files you downloaded from Actions UI
   - Uses --zips-dir <folder> or repeated --zip <file.zip>
   - Supports run subfolders like:
       artifacts/manual/1/*.zip
       artifacts/manual/2/*.zip
       artifacts/manual/3/*.zip
     Each immediate subfolder is treated as one "run".

2) EXTRACTED mode: point to a folder that ALREADY contains extracted artifact content
   - Uses --extracted-dir <folder>
   - Also works if you point --zips-dir to a folder with *no zip files* but with extracted subfolders.

Both modes can be used together (e.g. --zips-dir artifacts/manual --extracted-dir out2)
to merge zip-based and pre-extracted runs into a single analysis.

Outputs (under --out):
  artifacts_extracted/ (only in ZIP mode)
  files/ (collected *.jsonl/*.txt)
  summary.csv
  top_failures.csv
  errors_summary.csv
  grouped_errors.csv (+ grouped_errors.xlsx if openpyxl is available)
  extracted_tests/<test_id>/meta.json + extraction_report.json + error_variations.json
  extracted_tests/<test_id>/<run_id>.diff/.al/.txt + <run_id>_error.txt when available

This script focuses on:
- top failing tests across the provided runs
- error-message variations (if error_message exists)
- extracting generated test code/patch (if generated_patch/test_code exists)
"""

import argparse
import csv
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", (s or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s or "artifact"


def extract_zip_file(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)


def find_zip_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".zip":
        return [root]
    if root.is_dir():
        return sorted([p for p in root.rglob("*.zip") if p.is_file()])
    return []


def rglob_files(root: Path, pattern: str) -> list[Path]:
    return [p for p in root.rglob(pattern) if p.is_file()]


# ---------------------------- Grouped error reporting ----------------------------
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TIME_RE = re.compile(r"\[[0-2]\d:[0-5]\d:[0-5]\d\]")
_WINPATH_RE = re.compile(r"[A-Z]:\\[^\n]+")


def _normalize_error_message(msg: str) -> str:
    """Normalize error messages so similar failures group together."""
    if msg is None:
        return ""
    msg = str(msg).replace("\r\n", "\n")
    msg = _ANSI_RE.sub("", msg)
    msg = _TIME_RE.sub("[HH:MM:SS]", msg)
    msg = _WINPATH_RE.sub("<path>", msg)

    # Normalize common variable parts
    msg = re.sub(r"Setting test codeunit range '\d+'", "Setting test codeunit range '<id>'", msg)
    msg = re.sub(r"\bCodeunit\s+\d+\b", "Codeunit <id>", msg)
    msg = re.sub(r"\bline\s+\d+\b", "line <n>", msg, flags=re.IGNORECASE)
    msg = re.sub(r"Line No\. = '.*?'", "Line No. = '<n>'", msg)

    # Collapse whitespace and drop empty lines
    return "\n".join(ln.rstrip() for ln in msg.strip().splitlines() if ln.strip())


def _bucket_error(msg: str) -> str:
    m = (msg or "").lower()
    if "agent timed out" in m or "timed out" in m:
        return "timeout"
    if "build or publish failed" in m:
        return "build/publish"
    if "passed pre-patch" in m and "expected: fail" in m:
        return "expectation_mismatch_prepatch_pass"
    if "failed post-patch" in m and "expected: pass" in m:
        return "expectation_mismatch_postpatch_fail"
    if "ui handlers were not executed" in m:
        return "missing_ui_handler"
    if "must assign a lot number" in m or "must assign a serial number" in m or "checkitemtracking" in m:
        return "item_tracking_not_handled"
    if "assert.areequal failed" in m and ("integer" in m and "biginteger" in m):
        return "assert_type_mismatch"
    if "assert." in m and ("recordcount failed" in m or "areequal failed" in m or "isfalse failed" in m):
        return "assert_failed"
    return "other"


# ---------------------------- Record parsing ----------------------------
def try_parse_jsonl_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{") and line.endswith("}"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    return None


def split_kv_records(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("instance_id "):
        parts = re.split(r"\n(?=instance_id\s)", text)
        return [p.strip() for p in parts if p.strip()]
    return [text]


def parse_kv_record(block: str) -> dict[str, Any]:
    b = block.replace("\r\n", "\n").replace("\r", "\n")

    # Extract generated_patch multiline
    gen_patch = None
    m = re.search(r"\bgenerated_patch\s", b)
    if m:
        start = m.end()
        m2 = re.search(r"\nerror_message\s", b[start:])
        if m2:
            gen_patch = b[start : start + m2.start()]
            rest = b[start + m2.start() :]
            head = b[: m.start()]
        else:
            gen_patch = b[start:]
            rest = ""
            head = b[: m.start()]
    else:
        head = b
        rest = ""

    head_tokens = re.split(r"\s+", head.strip())
    data: dict[str, Any] = {}
    i = 0
    while i < len(head_tokens) - 1:
        key = head_tokens[i]
        val = head_tokens[i + 1]
        if key in {"instance_id", "project", "model", "agent_name", "category", "resolved", "build", "timeout"}:
            data[key] = val
            i += 2
        else:
            i += 1

    if gen_patch is not None:
        data["generated_patch"] = gen_patch.strip("\n")

    # Parse error_message from rest
    if rest:
        rm = re.search(r"\berror_message\s", rest)
        if rm:
            start = rm.end()
            stop = None
            for key2 in [" metrics ", " execution_time ", " llm_duration ", "\nmetrics ", "\nexecution_time "]:
                pos = rest.find(key2, start)
                if pos != -1:
                    stop = pos
                    break
            em = rest[start:].strip() if stop is None else rest[start:stop].strip()
            data["error_message"] = em

    # Coerce booleans
    for k in ["resolved", "build", "timeout"]:
        if k in data:
            v = str(data[k]).strip().lower()
            if v in ("true", "false"):
                data[k] = (v == "true")

    return data


def iter_records_from_file(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")

    # JSONL
    recs: list[dict[str, Any]] = []
    json_hits = 0
    for line in content.splitlines():
        obj = try_parse_jsonl_line(line)
        if obj is not None:
            recs.append(obj)
            json_hits += 1
    if json_hits:
        return recs

    # KV fallback
    return [parse_kv_record(block) for block in split_kv_records(content)]


def get_test_id(rec: dict[str, Any]) -> str:
    if isinstance(rec.get("instance_id"), str) and rec["instance_id"].strip():
        return rec["instance_id"].strip()
    for k in ["test_name", "testName", "name", "id", "testId", "test_id", "title"]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "unknown_test"


def get_category(rec: dict[str, Any]) -> str | None:
    v = rec.get("category")
    return v.strip() if isinstance(v, str) and v.strip() else None


def get_success_fail(rec: dict[str, Any]) -> str | None:
    # KV schema
    if isinstance(rec.get("resolved"), bool) or isinstance(rec.get("build"), bool) or isinstance(rec.get("timeout"), bool):
        resolved = rec.get("resolved")
        build = rec.get("build")
        timeout = rec.get("timeout")
        if resolved is True and build is True and timeout is False:
            return "success"
        return "fail"

    # Common JSON fields
    if isinstance(rec.get("passed"), bool):
        return "success" if rec["passed"] else "fail"
    if isinstance(rec.get("success"), bool):
        return "success" if rec["success"] else "fail"

    for k in ["status", "result", "outcome", "conclusion"]:
        v = rec.get(k)
        if isinstance(v, str):
            vl = v.strip().lower()
            if vl in ["passed", "pass", "success", "ok"]:
                return "success"
            if vl in ["failed", "fail", "error", "timeout", "cancelled", "canceled"]:
                return "fail"

    return None


def extract_code_text(rec: dict[str, Any]) -> tuple[str, str] | None:
    if isinstance(rec.get("generated_patch"), str) and rec["generated_patch"].strip():
        return (".diff", rec["generated_patch"])

    for k in ["test_code", "testCode", "generated_code", "generatedCode", "code", "al", "al_code", "source"]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            ext = ".al" if ("codeunit" in v.lower() or "procedure" in v.lower()) else ".txt"
            return (ext, v)

    return None


@dataclass
class Agg:
    total: int = 0
    success: int = 0
    fail: int = 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", dest="zips", action="append", default=[], help="Path to an artifact .zip (repeatable)")
    ap.add_argument(
        "--zips-dir",
        default=None,
        help=(
            "Directory containing artifact .zip files. If it contains run subfolders, each subfolder is treated as one run. "
            "If it contains no zips, it's treated as extracted content."
        ),
    )
    ap.add_argument("--extracted-dir", default=None, help="Directory containing already extracted artifact content")
    ap.add_argument("--zip-depth", type=int, default=3, help="How deep to extract nested zip files (ZIP mode)")
    ap.add_argument("--category", default="test-generation", help="Filter records by category")
    ap.add_argument("--top", type=int, default=10, help="How many top failing tests to extract")
    ap.add_argument("--out", default="out", help="Output directory")
    args = ap.parse_args()

    out_root = Path(args.out)
    extract_root = out_root / "artifacts_extracted"
    files_root = out_root / "files"
    out_root.mkdir(parents=True, exist_ok=True)
    files_root.mkdir(parents=True, exist_ok=True)

    # ---------- Decide input mode (both --zips-dir and --extracted-dir can be combined) ----------
    extracted_dirs: list[Path] = []

    # EXTRACTED mode: pre-extracted content folders
    if args.extracted_dir:
        root = Path(args.extracted_dir)
        if not root.exists():
            die(f"--extracted-dir does not exist: {root}")
        sub = [p for p in root.iterdir() if p.is_dir()]
        extracted_dirs = sorted(sub) if sub else [root]
        print(f"Using extracted content: {root} (runs={len(extracted_dirs)})")

    # ZIP mode: gather zip inputs and group by run folder when applicable
    run_groups: list[tuple[str, list[Path]]] = []

    # Group by immediate subfolders under --zips-dir (manual/1, manual/2, manual/3)
    if args.zips_dir:
        root_dir = Path(args.zips_dir)
        if root_dir.exists() and root_dir.is_dir():
            subdirs = sorted([d for d in root_dir.iterdir() if d.is_dir()])
            if subdirs:
                for sd in subdirs:
                    zips_in_sd = find_zip_files(sd)
                    if zips_in_sd:
                        run_groups.append((sd.name, zips_in_sd))

                # Also include zips directly under root as one group (optional)
                root_zips = sorted([z for z in root_dir.glob("*.zip") if z.is_file()])
                if root_zips:
                    run_groups.insert(0, (root_dir.name, root_zips))
            else:
                # No subdirs; treat root as a single run
                zips_in_root = find_zip_files(root_dir)
                if zips_in_root:
                    run_groups.append((root_dir.name, zips_in_root))

    # Explicit --zip files become their own run group if not already included
    explicit_zip_inputs: list[Path] = []
    for z in args.zips:
        explicit_zip_inputs.extend(find_zip_files(Path(z)))
    explicit_zip_inputs = sorted(set(explicit_zip_inputs))
    if explicit_zip_inputs:
        in_group = {zp for _, zs in run_groups for zp in zs}
        for zp in explicit_zip_inputs:
            if zp not in in_group:
                run_groups.append((zp.stem, [zp]))

    if run_groups:
        extract_root.mkdir(parents=True, exist_ok=True)
        for run_i, (run_name, zips_for_run) in enumerate(run_groups, start=1):
            tag = safe_name(run_name)
            dest = extract_root / f"{run_i:03d}_{tag}"
            dest.mkdir(parents=True, exist_ok=True)
            print(f"Extract run [{run_i}/{len(run_groups)}]: {run_name} (zips={len(zips_for_run)}) -> {dest}")

            for i, zip_path in enumerate(zips_for_run, start=1):
                zip_tag = safe_name(zip_path.stem)
                zip_dest = dest / f"{i:03d}_{zip_tag}"
                print(f"  - Extract zip [{i}/{len(zips_for_run)}]: {zip_path} -> {zip_dest}")
                extract_zip_file(zip_path, zip_dest)

                # Nested extraction inside this zip subtree
                cur_level = [zip_dest]
                for _depth in range(1, args.zip_depth + 1):
                    next_level: list[Path] = []
                    for d in cur_level:
                        for nested in rglob_files(d, "*.zip"):
                            nested_tag = safe_name(nested.stem)
                            nested_dest = nested.parent / f"{nested_tag}__unzipped"
                            if nested_dest.exists():
                                continue
                            try:
                                extract_zip_file(nested, nested_dest)
                                next_level.append(nested_dest)
                            except zipfile.BadZipFile:
                                continue
                    cur_level = next_level
                    if not cur_level:
                        break

            extracted_dirs.append(dest)
    elif not extracted_dirs:
        # No zips found and no extracted dirs. If --zips-dir exists, treat it as extracted content.
        if args.zips_dir and Path(args.zips_dir).exists():
            root = Path(args.zips_dir)
            sub = [d for d in root.iterdir() if d.is_dir()]
            extracted_dirs = sorted(sub) if sub else [root]
            print(f"No .zip files found under --zips-dir; treating as extracted content: {root} (runs={len(extracted_dirs)})")
        else:
            die("No .zip files found. Use --zip <file.zip> or --zips-dir <folder> or --extracted-dir <folder>.")

    print(f"\nTotal runs to analyze: {len(extracted_dirs)}")

    # ---------- Collect jsonl/txt per extracted run ----------
    run_index = 0
    for d in extracted_dirs:
        run_index += 1
        run_out = files_root / f"run-{run_index:03d}"
        run_out.mkdir(parents=True, exist_ok=True)

        candidates = rglob_files(d, "*.jsonl") + rglob_files(d, "*.txt")
        if not candidates:
            print(f"[run {run_index:03d}] No .jsonl/.txt found under {d}")
            continue

        seen: dict[str, int] = {}
        for p in candidates:
            base = p.name
            if base in seen:
                seen[base] += 1
                target = run_out / f"{seen[base]}_{base}"
            else:
                seen[base] = 0
                target = run_out / base
            target.write_bytes(p.read_bytes())

        print(f"[run {run_index:03d}] collected {len(candidates)} files -> {run_out}")

    # ---------- Analyze ----------
    category_filter = args.category.strip().lower()
    agg: dict[str, Agg] = {}
    rec_cache: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    for run_folder in sorted(files_root.glob("run-*")):
        run_id = run_folder.name
        for f in list(run_folder.glob("*.jsonl")) + list(run_folder.glob("*.txt")):
            for rec in iter_records_from_file(f):
                cat = get_category(rec)
                if category_filter and (not cat or cat.strip().lower() != category_filter):
                    continue

                tid = get_test_id(rec)
                status = get_success_fail(rec)
                if status is None:
                    continue

                a = agg.setdefault(tid, Agg())
                a.total += 1
                if status == "success":
                    a.success += 1
                else:
                    a.fail += 1

                rec_cache.setdefault(tid, []).append((run_id, rec))

    if not agg:
        die(f"No records found for category='{args.category}'.")

    summary_csv = out_root / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test_id", "category", "total", "success", "fail", "fail_rate"])
        for tid, a in sorted(agg.items(), key=lambda kv: (-kv[1].fail, kv[0].lower())):
            rate = (a.fail / a.total) if a.total else 0.0
            w.writerow([tid, args.category, a.total, a.success, a.fail, f"{rate:.4f}"])

    top = sorted(agg.items(), key=lambda kv: (kv[1].fail, kv[1].total), reverse=True)[: args.top]

    top_csv = out_root / "top_failures.csv"
    with top_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "test_id", "fail", "total", "fail_rate"])
        for i, (tid, a) in enumerate(top, start=1):
            rate = (a.fail / a.total) if a.total else 0.0
            w.writerow([i, tid, a.fail, a.total, f"{rate:.4f}"])

    # ---------- Error variations + extracted code per top failing test ----------
    extracted_tests_root = out_root / "extracted_tests"
    extracted_tests_root.mkdir(parents=True, exist_ok=True)

    errors_summary_csv = out_root / "errors_summary.csv"
    with errors_summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test_id", "error_rank", "count", "error_message"])

        for tid, a in top:
            test_folder = extracted_tests_root / safe_name(tid)
            test_folder.mkdir(parents=True, exist_ok=True)

            (test_folder / "meta.json").write_text(
                json.dumps(
                    {
                        "test_id": tid,
                        "category": args.category,
                        "total": a.total,
                        "success": a.success,
                        "fail": a.fail,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            saved = 0
            for run_id, rec in rec_cache.get(tid, [])[:10]:
                code_piece = extract_code_text(rec)
                if code_piece:
                    ext, txt = code_piece
                    (test_folder / f"{run_id}{ext}").write_text(txt, encoding="utf-8")
                    saved += 1

                em = rec.get("error_message")
                if isinstance(em, str) and em.strip():
                    (test_folder / f"{run_id}_error.txt").write_text(em, encoding="utf-8")

            (test_folder / "extraction_report.json").write_text(
                json.dumps({"code_snippets_saved": saved}, indent=2),
                encoding="utf-8",
            )

            variants: dict[str, int] = {}
            for _run_id, rec in rec_cache.get(tid, []):
                em = rec.get("error_message")
                if not isinstance(em, str):
                    continue
                em_norm = "\n".join([ln.rstrip() for ln in em.strip().splitlines()]).strip()
                if not em_norm:
                    continue
                variants[em_norm] = variants.get(em_norm, 0) + 1

            variants_sorted = sorted(variants.items(), key=lambda kv: kv[1], reverse=True)

            (test_folder / "error_variations.json").write_text(
                json.dumps(
                    {
                        "test_id": tid,
                        "total_failures": a.fail,
                        "distinct_error_messages": len(variants_sorted),
                        "variants": [{"count": c, "error_message": msg} for msg, c in variants_sorted],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            for rank, (msg, c) in enumerate(variants_sorted, start=1):
                msg_csv = msg if len(msg) <= 3000 else (msg[:3000] + "…")
                w.writerow([tid, rank, c, msg_csv])


    print("\nDONE ✅")
    if extract_root.exists():
        print(f"- Extracted zips -> {extract_root}")
    print(f"- Collected files -> {files_root}")
    print(f"- Summary -> {summary_csv}")
    print(f"- Top failures -> {top_csv}")
    print(f"- Error variations -> {errors_summary_csv}")
    print(f"- Extracted tests -> {extracted_tests_root}")


if __name__ == "__main__":
    main()
