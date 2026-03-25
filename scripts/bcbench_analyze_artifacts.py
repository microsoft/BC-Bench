#!/usr/bin/env python3
"""bcbench_analyze_artifacts.py

Analyze BC-Bench GitHub Actions artifacts that you already downloaded.

Supports TWO input modes (no GitHub API, no tokens):

1) ZIP mode: point to a folder of artifact .zip files you downloaded from Actions UI
   - Uses --zips-dir <folder> or repeated --zip <file.zip>

2) EXTRACTED mode: point to a folder that ALREADY contains extracted artifact content
   - Uses --extracted-dir <folder>
   - Also works if you point --zips-dir to a folder with *no zip files* but with extracted subfolders.

Outputs (under --out):
  artifacts_extracted/    (only in ZIP mode)
  files/                  (collected *.jsonl/*.txt)
  summary.csv
  top_failures.csv
  errors_summary.csv
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
from typing import Any, Dict, List, Optional, Tuple


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


def find_zip_files(root: Path) -> List[Path]:
    if root.is_file() and root.suffix.lower() == ".zip":
        return [root]
    if root.is_dir():
        return sorted([p for p in root.rglob("*.zip") if p.is_file()])
    return []


def rglob_files(root: Path, pattern: str) -> List[Path]:
    return [p for p in root.rglob(pattern) if p.is_file()]


# ---------------------------- Record parsing ----------------------------

def try_parse_jsonl_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{") and line.endswith("}"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    return None


def split_kv_records(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("instance_id "):
        parts = re.split(r"\n(?=instance_id\s)", text)
        return [p.strip() for p in parts if p.strip()]
    return [text]


def parse_kv_record(block: str) -> Dict[str, Any]:
    b = block.replace("\r\n", "\n").replace("\r", "\n")

    # Extract generated_patch multiline
    gen_patch = None
    m = re.search(r"\bgenerated_patch\s", b)
    if m:
        start = m.end()
        m2 = re.search(r"\nerror_message\s", b[start:])
        if m2:
            gen_patch = b[start:start + m2.start()]
            rest = b[start + m2.start():]
            head = b[:m.start()]
        else:
            gen_patch = b[start:]
            rest = ""
            head = b[:m.start()]
    else:
        head = b
        rest = ""

    head_tokens = re.split(r"\s+", head.strip())
    data: Dict[str, Any] = {}
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


def iter_records_from_file(path: Path) -> List[Dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")

    # JSONL
    recs: List[Dict[str, Any]] = []
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


def get_test_id(rec: Dict[str, Any]) -> str:
    if isinstance(rec.get("instance_id"), str) and rec["instance_id"].strip():
        return rec["instance_id"].strip()
    for k in ["test_name", "testName", "name", "id", "testId", "test_id", "title"]:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "unknown_test"


def get_category(rec: Dict[str, Any]) -> Optional[str]:
    v = rec.get("category")
    return v.strip() if isinstance(v, str) and v.strip() else None


def get_success_fail(rec: Dict[str, Any]) -> Optional[str]:
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


def extract_code_text(rec: Dict[str, Any]) -> Optional[Tuple[str, str]]:
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
    ap.add_argument("--zips-dir", default=None, help="Directory containing artifact .zip files (recursively). If it contains no zips, it's treated as extracted content.")
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

    # ---------- Decide input mode ----------
    extracted_dirs: List[Path] = []

    # EXTRACTED mode explicitly
    if args.extracted_dir:
        root = Path(args.extracted_dir)
        if not root.exists():
            die(f"--extracted-dir does not exist: {root}")
        sub = [p for p in root.iterdir() if p.is_dir()]
        extracted_dirs = sorted(sub) if sub else [root]
        print(f"Using extracted content: {root} (runs={len(extracted_dirs)})")

    else:
        # ZIP mode: gather zip inputs
        zip_inputs: List[Path] = []
        for z in args.zips:
            zip_inputs.extend(find_zip_files(Path(z)))
        if args.zips_dir:
            zip_inputs.extend(find_zip_files(Path(args.zips_dir)))

        zip_inputs = sorted(set(zip_inputs))

        if zip_inputs:
            # ZIP mode extraction
            extract_root.mkdir(parents=True, exist_ok=True)
            for i, zip_path in enumerate(zip_inputs, start=1):
                tag = safe_name(zip_path.stem)
                dest = extract_root / f"{i:03d}_{tag}"
                print(f"Extract [{i}/{len(zip_inputs)}]: {zip_path} -> {dest}")
                extract_zip_file(zip_path, dest)

                # Nested extraction
                cur_level = [dest]
                for _depth in range(1, args.zip_depth + 1):
                    next_level: List[Path] = []
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

        else:
            # No zips found. If --zips-dir was provided and exists, treat it as extracted content.
            if args.zips_dir and Path(args.zips_dir).exists():
                root = Path(args.zips_dir)
                sub = [p for p in root.iterdir() if p.is_dir()]
                extracted_dirs = sorted(sub) if sub else [root]
                print(f"No .zip files found under --zips-dir; treating as extracted content: {root} (runs={len(extracted_dirs)})")
            else:
                die("No .zip files found. Use --zip <file.zip> or --zips-dir <folder> or --extracted-dir <folder>.")

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
        seen: Dict[str, int] = {}
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
    agg: Dict[str, Agg] = {}
    rec_cache: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}

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
                json.dumps({
                    "test_id": tid,
                    "category": args.category,
                    "total": a.total,
                    "success": a.success,
                    "fail": a.fail,
                }, indent=2),
                encoding="utf-8",
            )

            saved = 0
            for run_id, rec in rec_cache.get(tid, [])[:10]:
                code_piece = extract_code_text(rec)
                if code_piece:
                    ext, text = code_piece
                    (test_folder / f"{run_id}{ext}").write_text(text, encoding="utf-8")
                    saved += 1
                em = rec.get("error_message")
                if isinstance(em, str) and em.strip():
                    (test_folder / f"{run_id}_error.txt").write_text(em, encoding="utf-8")

            (test_folder / "extraction_report.json").write_text(
                json.dumps({"code_snippets_saved": saved}, indent=2),
                encoding="utf-8",
            )

            variants: Dict[str, int] = {}
            for run_id, rec in rec_cache.get(tid, []):
                em = rec.get("error_message")
                if not isinstance(em, str):
                    continue
                em_norm = "\n".join([ln.rstrip() for ln in em.strip().splitlines()]).strip()
                if not em_norm:
                    continue
                variants[em_norm] = variants.get(em_norm, 0) + 1

            variants_sorted = sorted(variants.items(), key=lambda kv: kv[1], reverse=True)

            (test_folder / "error_variations.json").write_text(
                json.dumps({
                    "test_id": tid,
                    "total_failures": a.fail,
                    "distinct_error_messages": len(variants_sorted),
                    "variants": [{"count": c, "error_message": msg} for msg, c in variants_sorted],
                }, indent=2),
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
