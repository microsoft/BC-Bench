from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError
from unidiff.patch import PatchedFile

from bcbench.dataset import TestEntry
from bcbench.exceptions import GeneratedOutputError, GeneratedSubmissionError, NoTestsExtractedError
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


def _canonical_project_path(repo_path: Path, project_path: str) -> str:
    resolved_repo_path = repo_path.resolve()
    resolved_project_path = (resolved_repo_path / Path(project_path.replace("\\", "/"))).resolve()
    if not resolved_project_path.is_relative_to(resolved_repo_path):
        raise GeneratedSubmissionError(f"Allowed product project is outside repository: {project_path}")
    return resolved_project_path.relative_to(resolved_repo_path).as_posix().casefold()


def _validate_al_paths(changed_paths: tuple[str, ...]) -> None:
    for changed_path in changed_paths:
        if not changed_path.casefold().endswith(".al"):
            raise GeneratedSubmissionError(f"Only AL files may be changed: {changed_path}")


def _validate_test_change(patched_file: PatchedFile, changed_paths: tuple[str, ...]) -> None:
    if patched_file.is_removed_file:
        raise GeneratedSubmissionError(f"Test files may not be deleted: {changed_paths[0]}")
    if patched_file.is_rename:
        raise GeneratedSubmissionError(f"Test files may not be renamed: {changed_paths[0]} -> {changed_paths[1]}")
    if any(line.is_removed for hunk in patched_file for line in hunk):
        raise GeneratedSubmissionError(f"Test changes may not remove lines: {changed_paths[0]}")


def analyze_generated_bugfix_output(
    repo_path: Path,
    generated_patch: str,
    allowed_app_projects: Iterable[str] = (),
) -> GeneratedBugFixOutput:
    if not generated_patch.strip():
        raise GeneratedOutputError("Generated patch is blank.")

    try:
        patch_set = PatchSet(generated_patch)
    except UnidiffParseError as exc:
        raise GeneratedOutputError(f"Failed to parse generated patch: {exc}") from exc

    if not patch_set:
        raise GeneratedOutputError("Malformed generated patch: no patched files found.")

    fix_files: list[PatchedFile] = []
    test_files: list[PatchedFile] = []
    app_projects: list[str] = []
    test_projects: list[str] = []
    allowed_project_paths = {_canonical_project_path(repo_path, project_path) for project_path in allowed_app_projects}

    for patched_file in patch_set:
        changed_paths = _changed_paths(patched_file)
        _validate_al_paths(changed_paths)
        if not patched_file and not _is_complete_rename(patched_file):
            raise GeneratedOutputError(f"Malformed generated patch: {patched_file.path} has no hunks.")
        project_paths = [find_project_path(repo_path, file_path) for file_path in changed_paths]
        project_classifications = {is_test_project(project_path) for project_path in project_paths}
        if len(project_classifications) > 1:
            raise GeneratedSubmissionError(f"Cannot safely split rename between product and test projects: {changed_paths[0]} -> {changed_paths[1]}.")

        if project_classifications == {True}:
            _validate_test_change(patched_file, changed_paths)
            test_files.append(patched_file)
            test_projects.extend(project_paths)
        else:
            for project_path in project_paths:
                if _canonical_project_path(repo_path, project_path) not in allowed_project_paths:
                    raise GeneratedSubmissionError(f"Product project is not allowed: {project_path}")
            fix_files.append(patched_file)
            app_projects.extend(project_paths)

    if not fix_files:
        raise GeneratedSubmissionError("Agent produced tests but no product-code fix.")

    fix_patch = "".join(map(str, fix_files))
    test_patch = "".join(map(str, test_files))
    file_contents: dict[str, str] = {}
    for patched_file in test_files:
        target_path = _strip_diff_path_prefix(patched_file.target_file)
        file_path = repo_path / Path(target_path)
        if patched_file.target_file != "/dev/null" and file_path.is_file():
            file_contents[target_path] = file_path.read_text(encoding="utf-8")

    try:
        tests = extract_tests_from_patch(test_patch, file_contents)
    except NoTestsExtractedError as exc:
        raise GeneratedSubmissionError(str(exc)) from exc

    test_count = sum(len(test.functionName) for test in tests)
    if test_count != 1:
        raise GeneratedSubmissionError(f"Expected exactly one new test procedure, found {test_count}.")

    return GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(order_project_paths((), app_projects)),
        test_projects=tuple(order_project_paths((), test_projects)),
        tests=tuple(tests),
    )
