"""Counterfactual workspace extraction, patch regeneration, and entry creation."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from unidiff import PatchSet

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.config import get_config
from bcbench.dataset.counterfactual_entry import CounterfactualEntry
from bcbench.dataset.dataset_entry import TestEntry
from bcbench.logger import get_logger

if TYPE_CHECKING:
    from bcbench.dataset.dataset_entry import DatasetEntry

logger = get_logger(__name__)
_config = get_config()

WORKSPACE_METADATA_FILE = "workspace.json"


def extract_workspace(entry: DatasetEntry, output_dir: Path, repo_path: Path | None = None) -> Path:
    """Extract patch hunks into an editable workspace directory.

    Creates a workspace with before/after .al files for both fix and test patches.
    Users can then edit the 'after' files and regenerate patches.

    Args:
        entry: The base dataset entry to extract from
        output_dir: Directory to create the workspace in
        repo_path: Optional repo path for full-fidelity extraction

    Returns:
        Path to the created workspace directory
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if repo_path is not None:
        _extract_via_repo(entry, output_dir, repo_path)
    else:
        _extract_via_patch(entry.patch, output_dir, "fix")
        _extract_via_patch(entry.test_patch, output_dir, "test")

    metadata = {
        "entry_id": entry.instance_id,
        "mode": "repo" if repo_path is not None else "patch-only",
        "files": {
            "fix": extract_file_paths_from_patch(entry.patch),
            "test": extract_file_paths_from_patch(entry.test_patch),
        },
        "codeunit_ids": _extract_codeunit_ids_from_patch(entry.test_patch),
    }
    metadata_path = output_dir / WORKSPACE_METADATA_FILE
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info(f"Workspace created at {output_dir}")
    return output_dir


def _extract_via_repo(entry: DatasetEntry, output_dir: Path, repo_path: Path) -> None:
    from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo

    checkout_commit(repo_path, entry.base_commit)

    all_patches = [("fix", entry.patch), ("test", entry.test_patch)]
    all_file_paths: dict[str, list[str]] = {}

    for category, patch_str in all_patches:
        all_file_paths[category] = extract_file_paths_from_patch(patch_str)

    # Copy "before" files
    for category, file_paths in all_file_paths.items():
        for file_path in file_paths:
            src = repo_path / file_path
            dest = output_dir / category / "before" / file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            # New files won't exist in "before" — that's expected

    # Apply patches and copy "after" files
    apply_patch(repo_path, entry.patch, "fix patch")
    apply_patch(repo_path, entry.test_patch, "test patch")

    for category, file_paths in all_file_paths.items():
        for file_path in file_paths:
            src = repo_path / file_path
            dest = output_dir / category / "after" / file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    clean_repo(repo_path)


def _extract_via_patch(patch_str: str, output_dir: Path, category: str) -> None:
    """Extract before/after files from a patch using line-preserving reconstruction."""
    padded_files = _reconstruct_padded_files(patch_str)

    for file_path, (before_lines, after_lines) in padded_files.items():
        before_dest = output_dir / category / "before" / file_path
        after_dest = output_dir / category / "after" / file_path

        before_dest.parent.mkdir(parents=True, exist_ok=True)
        after_dest.parent.mkdir(parents=True, exist_ok=True)

        before_dest.write_text("".join(before_lines), encoding="utf-8")
        after_dest.write_text("".join(after_lines), encoding="utf-8")


def _reconstruct_padded_files(patch_str: str) -> dict[str, tuple[list[str], list[str]]]:
    """Reconstruct padded before/after file content from a patch.

    Preserves original line numbers by padding with empty lines so that
    difflib.unified_diff produces correct @@ headers when regenerating patches.

    Returns:
        Dict mapping file paths to (before_lines, after_lines) tuples.
    """
    patch_set = PatchSet(patch_str)
    result: dict[str, tuple[list[str], list[str]]] = {}

    for patched_file in patch_set:
        if not patched_file.path:
            continue

        before_lines: list[str] = []
        after_lines: list[str] = []

        for hunk in patched_file:
            # Pad before_lines up to hunk start (1-indexed → 0-indexed)
            source_start = hunk.source_start
            while len(before_lines) < source_start - 1:
                before_lines.append("\n")
                after_lines.append("\n")

            for line in hunk:
                if line.is_context:
                    before_lines.append(str(line.value))
                    after_lines.append(str(line.value))
                elif line.source_line_no is not None:
                    # Removed line (only in before)
                    before_lines.append(str(line.value))
                elif line.target_line_no is not None:
                    # Added line (only in after)
                    after_lines.append(str(line.value))

        result[patched_file.path] = (before_lines, after_lines)

    return result


def regenerate_patches(workspace_dir: Path) -> tuple[str, str]:
    """Regenerate fix and test patches from workspace before/after files.

    Args:
        workspace_dir: Path to the workspace directory

    Returns:
        Tuple of (fix_patch, test_patch) strings in git-compatible format
    """
    metadata = _load_workspace_metadata(workspace_dir)

    fix_patch = _regenerate_category_patch(workspace_dir, "fix", metadata["files"]["fix"])
    test_patch = _regenerate_category_patch(workspace_dir, "test", metadata["files"]["test"])

    return fix_patch, test_patch


def _regenerate_category_patch(workspace_dir: Path, category: str, file_paths: list[str]) -> str:
    """Regenerate a combined patch for all files in a category."""
    parts: list[str] = []

    for file_path in file_paths:
        before_path = workspace_dir / category / "before" / file_path
        after_path = workspace_dir / category / "after" / file_path

        before_lines = before_path.read_text(encoding="utf-8").splitlines(keepends=True) if before_path.exists() else []
        after_lines = after_path.read_text(encoding="utf-8").splitlines(keepends=True) if after_path.exists() else []

        diff = _generate_git_diff(before_lines, after_lines, file_path)
        if diff:
            parts.append(diff)

    return "".join(parts)


def _generate_git_diff(before_lines: list[str], after_lines: list[str], file_path: str) -> str:
    """Generate a single file diff in git-compatible format."""
    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )

    if not diff_lines:
        return ""

    # Prepend git diff header
    header = f"diff --git a/{file_path} b/{file_path}\n"
    return header + "".join(diff_lines)


def create_cf_entry(
    workspace_dir: Path,
    variant_description: str,
    intervention_type: str | None = None,
    fail_to_pass_override: list[TestEntry] | None = None,
    cf_path: Path | None = None,
    problem_statement_dir: Path | None = None,
) -> CounterfactualEntry:
    """Create a counterfactual entry from an edited workspace.

    Args:
        workspace_dir: Path to the workspace directory
        variant_description: Description of the counterfactual variant
        intervention_type: Optional type of intervention
        fail_to_pass_override: Override auto-detected FAIL_TO_PASS tests
        cf_path: Override path to counterfactual JSONL file
        problem_statement_dir: Override path to problem statement directory

    Returns:
        The created CounterfactualEntry (also appended to counterfactual.jsonl)
    """
    metadata = _load_workspace_metadata(workspace_dir)
    base_instance_id: str = metadata["entry_id"]

    fix_patch, test_patch = regenerate_patches(workspace_dir)

    if cf_path is None:
        cf_path = _config.paths.counterfactual_dataset_path
    if problem_statement_dir is None:
        problem_statement_dir = _config.paths.problem_statement_dir

    instance_id = _next_cf_id(base_instance_id, cf_path)

    if fail_to_pass_override is not None:
        fail_to_pass = fail_to_pass_override
    else:
        # Build file_contents from workspace test files for codeunit ID resolution
        test_file_contents = _read_workspace_file_contents(workspace_dir, "test")
        # Also use stored codeunit IDs from original patch extraction
        stored_codeunit_ids = metadata.get("codeunit_ids", {})
        fail_to_pass = _detect_fail_to_pass(test_patch, base_instance_id, test_file_contents, stored_codeunit_ids)

    problem_statement_path = _scaffold_problem_statement(instance_id, base_instance_id, problem_statement_dir)

    cf_entry = CounterfactualEntry(
        instance_id=instance_id,
        base_instance_id=base_instance_id,
        variant_description=variant_description,
        intervention_type=intervention_type,
        test_patch=test_patch,
        patch=fix_patch,
        fail_to_pass=fail_to_pass,
        problem_statement_override=problem_statement_path,
    )

    _append_cf_entry(cf_entry, cf_path)

    logger.info(f"Created counterfactual entry: {instance_id}")
    return cf_entry


def _load_workspace_metadata(workspace_dir: Path) -> dict:
    metadata_path = workspace_dir / WORKSPACE_METADATA_FILE
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _read_workspace_file_contents(workspace_dir: Path, category: str) -> dict[str, str]:
    """Read all 'after' file contents from a workspace category."""
    contents: dict[str, str] = {}
    after_dir = workspace_dir / category / "after"
    if after_dir.exists():
        for file_path in after_dir.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(after_dir)).replace("\\", "/")
                contents[rel_path] = file_path.read_text(encoding="utf-8")
    return contents


def _extract_codeunit_ids_from_patch(patch_str: str) -> dict[str, int]:
    """Extract codeunit IDs per file from a patch (using hunk headers and context lines)."""
    result: dict[str, int] = {}
    patch_set = PatchSet(patch_str)
    for patched_file in patch_set:
        if not patched_file.path:
            continue
        for hunk in patched_file:
            if patched_file.path not in result and hasattr(hunk, "section_header") and hunk.section_header:
                match = re.search(r'codeunit\s+(\d+)\s+"[^"]*"', hunk.section_header)
                if match:
                    result[patched_file.path] = int(match.group(1))
            for line in hunk:
                if patched_file.path not in result and line.source_line_no is not None:
                    match = re.search(r'codeunit\s+(\d+)\s+"[^"]*"', str(line.value))
                    if match:
                        result[patched_file.path] = int(match.group(1))
    return result


def _next_cf_id(base_instance_id: str, cf_path: Path) -> str:
    """Determine the next available __cf-N id for the given base entry."""
    existing_numbers: list[int] = []
    pattern = re.compile(re.escape(base_instance_id) + r"__cf-(\d+)$")

    if cf_path.exists():
        with open(cf_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                data = json.loads(stripped)
                match = pattern.match(data.get("instance_id", ""))
                if match:
                    existing_numbers.append(int(match.group(1)))

    next_num = max(existing_numbers, default=0) + 1
    return f"{base_instance_id}__cf-{next_num}"


def _detect_fail_to_pass(
    test_patch: str,
    base_instance_id: str,
    file_contents: dict[str, str] | None = None,
    stored_codeunit_ids: dict[str, int] | None = None,
) -> list[TestEntry]:
    """Auto-detect FAIL_TO_PASS test entries from a test patch.

    Finds [Test] procedure declarations in the patch and resolves codeunit IDs
    from patch context lines, file_contents, stored metadata, or base entry data.
    """
    patch_set = PatchSet(test_patch)
    codeunit_functions: dict[int, set[str]] = {}

    for patched_file in patch_set:
        if not patched_file.path or not patched_file.path.lower().endswith(".codeunit.al"):
            continue

        # Single pass: extract codeunit ID and [Test] procedures together
        codeunit_id: int | None = None
        found_test_attr = False
        pending_funcs: set[str] = set()

        for hunk in patched_file:
            # Check hunk section header for codeunit ID
            if codeunit_id is None and hasattr(hunk, "section_header") and hunk.section_header:
                match = re.search(r'codeunit\s+(\d+)\s+"[^"]*"', hunk.section_header)
                if match:
                    codeunit_id = int(match.group(1))

            for line in hunk:
                line_value = str(line.value).strip()

                # Check context/removed lines for codeunit ID
                if codeunit_id is None and line.source_line_no is not None:
                    match = re.search(r'codeunit\s+(\d+)\s+"[^"]*"', str(line.value))
                    if match:
                        codeunit_id = int(match.group(1))

                # Detect [Test] + procedure in added lines only
                is_added = line.target_line_no is not None and line.source_line_no is None
                if not is_added:
                    continue

                if re.match(r"\[Test\]", line_value, re.IGNORECASE):
                    found_test_attr = True
                    continue

                if found_test_attr:
                    proc_match = re.match(r"procedure\s+(\w+)\s*\(", line_value)
                    if proc_match:
                        pending_funcs.add(proc_match.group(1))
                        found_test_attr = False
                    elif line_value and not line_value.startswith("["):
                        found_test_attr = False

        # Resolve codeunit ID from file_contents
        if codeunit_id is None and file_contents and patched_file.path in file_contents:
            match = re.search(r'codeunit\s+(\d+)\s+"[^"]*"', file_contents[patched_file.path])
            if match:
                codeunit_id = int(match.group(1))

        # Resolve from stored workspace metadata
        if codeunit_id is None and stored_codeunit_ids and patched_file.path in stored_codeunit_ids:
            codeunit_id = stored_codeunit_ids[patched_file.path]

        # Fall back to base entry's FAIL_TO_PASS
        if codeunit_id is None:
            codeunit_id = _resolve_codeunit_id_from_base(patched_file.path, base_instance_id)

        if codeunit_id is not None and pending_funcs:
            codeunit_functions.setdefault(codeunit_id, set()).update(pending_funcs)
        elif pending_funcs:
            logger.warning(f"Could not resolve codeunit ID for {patched_file.path}")

    if not codeunit_functions:
        raise ValueError("No [Test] procedures found in test patch")

    return [TestEntry(codeunitID=cid, functionName=frozenset(funcs)) for cid, funcs in codeunit_functions.items()]


def _resolve_codeunit_id_from_base(file_path: str, base_instance_id: str) -> int | None:
    """Resolve codeunit ID from the base entry's FAIL_TO_PASS data."""
    from bcbench.dataset.dataset_loader import load_dataset_entries

    try:
        entries = load_dataset_entries(_config.paths.dataset_path, entry_id=base_instance_id)
        if entries:
            base_entry = entries[0]
            # Extract codeunit IDs from test_patch of the base entry for matching file paths
            base_test_files = extract_file_paths_from_patch(base_entry.test_patch)
            if file_path in base_test_files and base_entry.fail_to_pass:
                return base_entry.fail_to_pass[0].codeunitID
    except Exception:
        logger.warning(f"Could not resolve codeunit ID from base entry {base_instance_id}")
    return None


def _scaffold_problem_statement(cf_instance_id: str, base_instance_id: str, ps_dir: Path | None = None) -> str:
    """Create a problem statement directory for the CF entry, copying from base."""
    if ps_dir is None:
        ps_dir = _config.paths.problem_statement_dir
    cf_dir = ps_dir / cf_instance_id
    base_dir = ps_dir / base_instance_id
    readme_name = _config.file_patterns.problem_statement_readme

    cf_dir.mkdir(parents=True, exist_ok=True)

    base_readme = base_dir / readme_name
    cf_readme = cf_dir / readme_name

    if base_readme.exists():
        content = base_readme.read_text(encoding="utf-8")
        cf_readme.write_text(content, encoding="utf-8")
        logger.info(f"Scaffolded problem statement from {base_readme}")
    else:
        cf_readme.write_text(
            f"# Problem Statement\n\nCounterfactual variant of {base_instance_id}.\n\nTODO: Edit this problem statement.\n",
            encoding="utf-8",
        )
        logger.info(f"Created placeholder problem statement at {cf_readme}")

    return f"{ps_dir.parent.name}/{ps_dir.name}/{cf_instance_id}"


def _append_cf_entry(cf_entry: CounterfactualEntry, cf_path: Path) -> None:
    """Append a counterfactual entry to the JSONL file."""
    cf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cf_path, "a", encoding="utf-8") as f:
        json.dump(cf_entry.model_dump(by_alias=True, mode="json"), f, ensure_ascii=False)
        f.write("\n")
