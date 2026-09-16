import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError
from unidiff.patch import PatchedFile

from bcbench.dataset import TestEntry
from bcbench.exceptions import GeneratedOutputError, GeneratedSubmissionError, NoTestsExtractedError, ProjectDiscoveryError, TestExtractionError
from bcbench.operations import (
    added_lines_belong_to_members,
    extract_executable_member_occurrences_from_content,
    find_project_path,
    has_only_codeunit_wrapper_outside_members,
    is_test_project,
    normalize_test_occurrences,
    order_project_paths,
    resolve_trusted_commit,
)
from bcbench.operations.patch_operations import GitDiffPaths, decode_git_header_path, extract_git_diff_paths, split_git_diff_blocks
from bcbench.operations.test_operations import ExecutableMemberOccurrence, TestOccurrence, extract_codeunit_id_from_content

_CONDITIONAL_COMPILATION_DIRECTIVE = re.compile(r"^\s*#\s*(?:if|elif|elseif|else|endif)\b", re.IGNORECASE)
_TEST_HANDLER_ATTRIBUTES = frozenset(
    attribute.casefold()
    for attribute in (
        "MessageHandler",
        "ConfirmHandler",
        "StrMenuHandler",
        "ModalPageHandler",
        "PageHandler",
        "ReportHandler",
        "RequestPageHandler",
        "SendNotificationHandler",
        "RecallNotificationHandler",
        "HyperlinkHandler",
    )
)


@dataclass(frozen=True)
class GeneratedBugFixOutput:
    full_patch: str
    fix_patch: str
    test_patch: str
    app_projects: tuple[str, ...]
    test_projects: tuple[str, ...]
    tests: tuple[TestEntry, ...]


@dataclass(frozen=True)
class _ParsedPatchFile:
    original_patch: str
    patched_file: PatchedFile
    paths: GitDiffPaths


def _normalize_repo_path(file_path: str) -> str:
    return file_path.replace("\\", "/")


def _changed_paths(paths: GitDiffPaths) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalize_repo_path(file_path) for file_path in (paths.source, paths.target) if file_path != "/dev/null"))


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


def _validate_no_added_conditional_compilation_directives(patched_file: PatchedFile, changed_paths: tuple[str, ...]) -> None:
    if any(line.is_added and _CONDITIONAL_COMPILATION_DIRECTIVE.match(line.value) for hunk in patched_file for line in hunk):
        raise GeneratedSubmissionError(f"Conditional compilation directives may not be added to test files: {changed_paths[-1]}")


def _contains_binary_metadata(diff_block: str) -> bool:
    return any(line == "GIT binary patch" or line.startswith("Binary files ") for line in diff_block.splitlines())


def _is_mode_only_change(diff_block: str) -> bool:
    metadata_lines = diff_block.splitlines()
    return (
        any(line.startswith("old mode ") for line in metadata_lines)
        and any(line.startswith("new mode ") for line in metadata_lines)
        and not any(line.startswith(("@@ ", "--- ", "+++ ", "rename from ", "rename to ")) for line in metadata_lines)
    )


def _normalize_diff_block(diff_block: str, paths: GitDiffPaths) -> str:
    same_path = _normalize_repo_path(paths.source) == _normalize_repo_path(paths.target)
    source_placeholder = "a/__bcbench_file__.al"
    target_placeholder = "b/__bcbench_file__.al" if same_path else "b/__bcbench_target__.al"
    normalized_lines: list[str] = []
    in_hunk = False

    for line in diff_block.splitlines(keepends=True):
        if line.startswith("diff --git "):
            line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            normalized_lines.append(f"diff --git {source_placeholder} {target_placeholder}{line_ending}")
        elif line.startswith("@@ "):
            in_hunk = True
            normalized_lines.append(line)
        elif not in_hunk and line.startswith("--- "):
            line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            source_header = "/dev/null" if paths.source == "/dev/null" else source_placeholder
            normalized_lines.append(f"--- {source_header}{line_ending}")
        elif not in_hunk and line.startswith("+++ "):
            line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            target_header = "/dev/null" if paths.target == "/dev/null" else target_placeholder
            normalized_lines.append(f"+++ {target_header}{line_ending}")
        else:
            normalized_lines.append(line)

    return "".join(normalized_lines)


def _parse_patch_files(generated_patch: str) -> tuple[_ParsedPatchFile, ...]:
    diff_blocks = split_git_diff_blocks(generated_patch)
    if not diff_blocks:
        raise GeneratedOutputError("Malformed generated patch: no patched files found.")

    parsed_files: list[_ParsedPatchFile] = []
    for diff_block in diff_blocks:
        if _contains_binary_metadata(diff_block):
            raise GeneratedSubmissionError("Binary AL changes are not allowed.")
        if _is_mode_only_change(diff_block):
            raise GeneratedSubmissionError("Mode-only AL changes are not allowed.")

        paths = extract_git_diff_paths(diff_block)
        normalized_block = _normalize_diff_block(diff_block, paths) if paths is not None else diff_block
        try:
            patch_set = PatchSet(normalized_block)
        except UnidiffParseError as exc:
            raise GeneratedOutputError(f"Failed to parse generated patch: {exc}") from exc
        if len(patch_set) != 1:
            raise GeneratedOutputError("Malformed generated patch: expected one patched file per diff block.")

        patched_file = patch_set[0]
        if paths is None:
            paths = GitDiffPaths(
                source=decode_git_header_path(patched_file.source_file),
                target=decode_git_header_path(patched_file.target_file),
            )
        parsed_files.append(_ParsedPatchFile(original_patch=diff_block, patched_file=patched_file, paths=paths))

    return tuple(parsed_files)


def _read_trusted_file(repo_path: Path, trusted_commit: str, file_path: str) -> str | None:
    tree_result = subprocess.run(
        ["git", "--no-replace-objects", "ls-tree", "--name-only", trusted_commit, "--", file_path],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    if not tree_result.stdout.strip():
        return None

    return subprocess.run(
        ["git", "--no-replace-objects", "show", f"{trusted_commit}:{file_path}"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout


def _is_allowed_new_test_member(member: ExecutableMemberOccurrence) -> bool:
    attributes = tuple(attribute.casefold() for attribute in member.attributes)
    if member.kind != "procedure":
        return False
    if member.is_test:
        test_attribute_count = attributes.count("test")
        handler_functions_count = attributes.count("handlerfunctions")
        return test_attribute_count == 1 and handler_functions_count <= 1 and len(attributes) == test_attribute_count + handler_functions_count
    return member.access_modifier == "local" and all(attribute in _TEST_HANDLER_ATTRIBUTES for attribute in attributes)


def _find_generated_test_occurrences(
    repo_path: Path,
    trusted_commit: str,
    test_files: Iterable[_ParsedPatchFile],
) -> tuple[TestOccurrence, ...]:
    generated_occurrences: list[TestOccurrence] = []
    pending_audits: list[tuple[str, str, bool, set[int], tuple[ExecutableMemberOccurrence, ...]]] = []
    parsed_files_by_target: dict[str, list[_ParsedPatchFile]] = defaultdict(list)
    for parsed_file in test_files:
        parsed_files_by_target[_normalize_repo_path(parsed_file.paths.target)].append(parsed_file)

    for target_path, parsed_files in parsed_files_by_target.items():
        file_path = repo_path / Path(target_path)
        if not file_path.is_file():
            raise GeneratedSubmissionError(f"Test file does not exist after generated changes: {target_path}")

        trusted_content = _read_trusted_file(repo_path, trusted_commit, target_path)
        baseline_content = trusted_content or ""
        final_content = file_path.read_text(encoding="utf-8")
        baseline_members = extract_executable_member_occurrences_from_content(baseline_content)
        final_members = extract_executable_member_occurrences_from_content(final_content)
        added_target_lines = {line.target_line_no for parsed_file in parsed_files for hunk in parsed_file.patched_file for line in hunk if line.is_added and line.target_line_no is not None}
        final_members_by_identity = {member.identity: member for member in final_members}
        for baseline_member in baseline_members:
            final_member = final_members_by_identity.get(baseline_member.identity)
            if (
                final_member is None
                or final_member.semantic_tokens != baseline_member.semantic_tokens
                or any(final_member.start_line <= line_number <= final_member.end_line for line_number in added_target_lines)
            ):
                raise GeneratedSubmissionError(f"Existing test behavior modified: {target_path}")

        baseline_member_identities = {member.identity for member in baseline_members}
        new_members = tuple(member for member in final_members if member.identity not in baseline_member_identities)
        pending_audits.append((target_path, final_content, trusted_content is None, added_target_lines, new_members))

        baseline_test_identities = {member.identity for member in baseline_members if member.kind == "procedure" and member.is_test}
        final_test_members = tuple(member for member in final_members if member.kind == "procedure" and member.is_test)
        final_test_identities = {member.identity for member in final_test_members}
        if not baseline_test_identities.issubset(final_test_identities):
            raise GeneratedSubmissionError(f"Existing test behavior modified: {target_path}")

        new_test_members = tuple(member for member in final_test_members if member.identity not in baseline_test_identities)
        if new_test_members:
            codeunit_id = extract_codeunit_id_from_content(final_content, target_path)
            generated_occurrences.extend(
                TestOccurrence(
                    codeunit_id=codeunit_id,
                    function_name=member.name,
                    start_line=member.start_line,
                    end_line=member.end_line,
                )
                for member in new_test_members
            )

    if not generated_occurrences:
        raise NoTestsExtractedError
    for target_path, final_content, is_new_file, added_target_lines, new_members in pending_audits:
        if any(not _is_allowed_new_test_member(member) for member in new_members):
            raise GeneratedSubmissionError(f"Invalid addition to test file: {target_path}")
        if is_new_file:
            if not has_only_codeunit_wrapper_outside_members(final_content, new_members):
                raise GeneratedSubmissionError(f"Invalid addition to test file: {target_path}")
        elif not added_lines_belong_to_members(final_content, added_target_lines, new_members):
            raise GeneratedSubmissionError(f"Invalid addition to test file: {target_path}")
    return tuple(generated_occurrences)


def analyze_generated_bugfix_output(
    repo_path: Path,
    generated_patch: str,
    trusted_commit: str,
    allowed_app_projects: Iterable[str] = (),
) -> GeneratedBugFixOutput:
    resolved_trusted_commit = resolve_trusted_commit(repo_path, trusted_commit)
    if not generated_patch.strip():
        raise GeneratedOutputError("Generated patch is blank.")

    parsed_files = _parse_patch_files(generated_patch)

    fix_files: list[_ParsedPatchFile] = []
    test_files: list[_ParsedPatchFile] = []
    app_projects: list[str] = []
    test_projects: list[str] = []
    allowed_project_paths = {_canonical_project_path(repo_path, project_path) for project_path in allowed_app_projects}

    for parsed_file in parsed_files:
        patched_file = parsed_file.patched_file
        changed_paths = _changed_paths(parsed_file.paths)
        _validate_al_paths(changed_paths)
        if not patched_file and not _is_complete_rename(patched_file):
            raise GeneratedOutputError(f"Malformed generated patch: {patched_file.path} has no hunks.")
        try:
            project_paths = [find_project_path(repo_path, file_path) for file_path in changed_paths]
        except ProjectDiscoveryError as exc:
            raise GeneratedSubmissionError(str(exc)) from exc
        project_classifications = {is_test_project(project_path) for project_path in project_paths}
        if len(project_classifications) > 1:
            raise GeneratedSubmissionError(f"Cannot safely split rename between product and test projects: {changed_paths[0]} -> {changed_paths[1]}.")

        if project_classifications == {True}:
            _validate_test_change(patched_file, changed_paths)
            _validate_no_added_conditional_compilation_directives(patched_file, changed_paths)
            test_files.append(parsed_file)
            test_projects.extend(project_paths)
        else:
            for project_path in project_paths:
                if _canonical_project_path(repo_path, project_path) not in allowed_project_paths:
                    raise GeneratedSubmissionError(f"Product project is not allowed: {project_path}")
            fix_files.append(parsed_file)
            app_projects.extend(project_paths)

    if not fix_files:
        raise GeneratedSubmissionError("Agent produced tests but no product-code fix.")

    fix_patch = "".join(parsed_file.original_patch for parsed_file in fix_files)
    test_patch = "".join(parsed_file.original_patch for parsed_file in test_files)

    try:
        test_occurrences = _find_generated_test_occurrences(repo_path, resolved_trusted_commit, test_files)
    except (NoTestsExtractedError, TestExtractionError) as exc:
        raise GeneratedSubmissionError(str(exc)) from exc

    test_count = len(test_occurrences)
    if test_count != 1:
        raise GeneratedSubmissionError(f"Expected exactly one new test procedure, found {test_count}.")
    tests = normalize_test_occurrences(test_occurrences)

    return GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(order_project_paths((), app_projects)),
        test_projects=tuple(order_project_paths((), test_projects)),
        tests=tuple(tests),
    )
