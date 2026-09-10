from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet
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


def analyze_generated_bugfix_output(repo_path: Path, generated_patch: str) -> GeneratedBugFixOutput:
    patch_set = PatchSet(generated_patch)
    fix_files: list[PatchedFile] = []
    test_files: list[PatchedFile] = []
    app_projects: list[str] = []
    test_projects: list[str] = []

    for patched_file in patch_set:
        project_path = find_project_path(repo_path, patched_file.path)
        if is_test_project(project_path):
            test_files.append(patched_file)
            test_projects.append(project_path)
        else:
            fix_files.append(patched_file)
            app_projects.append(project_path)

    if not fix_files:
        raise GeneratedOutputError("Agent produced tests but no product-code fix.")

    fix_patch = "".join(map(str, fix_files))
    test_patch = "".join(map(str, test_files))
    file_contents: dict[str, str] = {}
    for patched_file in test_files:
        file_path = repo_path / Path(patched_file.path.replace("\\", "/"))
        if file_path.is_file():
            file_contents[patched_file.path] = file_path.read_text(encoding="utf-8")

    tests = extract_tests_from_patch(test_patch, file_contents)

    return GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(order_project_paths((), app_projects)),
        test_projects=tuple(order_project_paths((), test_projects)),
        tests=tuple(tests),
    )
