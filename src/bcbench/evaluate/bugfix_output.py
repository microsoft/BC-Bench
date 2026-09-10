from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError
from unidiff.patch import PatchedFile

from bcbench.dataset import TestEntry
from bcbench.exceptions import GeneratedOutputError
from bcbench.operations import extract_tests_from_patch, find_project_path, is_test_project, order_project_paths


@dataclass(frozen=True)
class GeneratedBugFixOutput:
    full_patch: str
    fix_patch: str
    test_patch: str
    app_projects: tuple[str, ...]
    test_projects: tuple[str, ...]
    tests: tuple[TestEntry, ...]


def _strip_diff_path_prefix(file_path: str) -> str:
    normalized_path = file_path.replace("\\", "/")
    if normalized_path.startswith(("a/", "b/")):
        return normalized_path[2:]
    return normalized_path


def _changed_paths(patched_file: PatchedFile) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_strip_diff_path_prefix(file_path) for file_path in (patched_file.source_file, patched_file.target_file) if file_path != "/dev/null"))


def _is_complete_rename(patched_file: PatchedFile) -> bool:
    patch_info_lines = str(patched_file.patch_info).splitlines()
    return patched_file.is_rename and any(line.startswith("rename from ") for line in patch_info_lines) and any(line.startswith("rename to ") for line in patch_info_lines)


def _validate_patch_structure(patch_set: PatchSet) -> None:
    if not patch_set:
        raise GeneratedOutputError("Malformed generated patch: no patched files found.")

    for patched_file in patch_set:
        if not patched_file and not _is_complete_rename(patched_file):
            raise GeneratedOutputError(f"Malformed generated patch: {patched_file.path} has no hunks.")


def analyze_generated_bugfix_output(repo_path: Path, generated_patch: str) -> GeneratedBugFixOutput:
    if not generated_patch.strip():
        raise GeneratedOutputError("Generated patch is blank.")

    try:
        patch_set = PatchSet(generated_patch)
    except UnidiffParseError as exc:
        raise GeneratedOutputError(f"Failed to parse generated patch: {exc}") from exc

    _validate_patch_structure(patch_set)

    fix_files: list[PatchedFile] = []
    test_files: list[PatchedFile] = []
    app_projects: list[str] = []
    test_projects: list[str] = []

    for patched_file in patch_set:
        changed_paths = _changed_paths(patched_file)
        project_paths = [find_project_path(repo_path, file_path) for file_path in changed_paths]
        project_classifications = {is_test_project(project_path) for project_path in project_paths}
        if len(project_classifications) > 1:
            raise GeneratedOutputError(f"Cannot safely split rename between product and test projects: {changed_paths[0]} -> {changed_paths[1]}.")

        if project_classifications == {True}:
            test_files.append(patched_file)
            test_projects.extend(project_paths)
        else:
            fix_files.append(patched_file)
            app_projects.extend(project_paths)

    if not fix_files:
        raise GeneratedOutputError("Agent produced tests but no product-code fix.")

    fix_patch = "".join(map(str, fix_files))
    test_patch = "".join(map(str, test_files))
    file_contents: dict[str, str] = {}
    for patched_file in test_files:
        target_path = _strip_diff_path_prefix(patched_file.target_file)
        file_path = repo_path / Path(target_path)
        if patched_file.target_file != "/dev/null" and file_path.is_file():
            file_contents[target_path] = file_path.read_text(encoding="utf-8")

    tests = extract_tests_from_patch(test_patch, file_contents)

    return GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(order_project_paths((), app_projects)),
        test_projects=tuple(order_project_paths((), test_projects)),
        tests=tuple(tests),
    )
