import re
from collections.abc import Iterable
from dataclasses import dataclass

from bcbench.dataset import TestEntry
from bcbench.exceptions import NoTestsExtractedError, TestExtractionError
from bcbench.logger import get_logger
from bcbench.operations.patch_operations import extract_git_diff_paths, split_git_diff_blocks

logger = get_logger(__name__)


@dataclass(frozen=True)
class TestOccurrence:
    codeunit_id: int
    function_name: str


def extract_codeunit_id_from_content(content: str, file_path: str) -> int:
    """Extract codeunit ID from AL file content.

    Args:
        content: The content of the AL file
        file_path: File path for error reporting

    Returns:
        Codeunit ID (always returns int, raises exception if not found)
    """
    codeunit_pattern = r'\bcodeunit\s+(\d+)\s+(?:"(?:[^"]|"")*"|[^\W\d]\w*)'
    match = re.search(codeunit_pattern, content, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    raise TestExtractionError(f"No codeunit ID found in {file_path}")


def extract_test_occurrences_from_patch(generated_patch: str, file_contents: dict[str, str]) -> tuple[TestOccurrence, ...]:
    occurrences: list[TestOccurrence] = []
    procedure_pattern = re.compile(r"^\+\s*procedure\s+(\w+)\s*\(", flags=re.IGNORECASE)
    test_attribute_pattern = re.compile(r"^\+\s*\[Test\]", flags=re.IGNORECASE)

    for diff_block in split_git_diff_blocks(generated_patch):
        paths = extract_git_diff_paths(diff_block)
        if paths is None or paths.target == "/dev/null":
            continue

        current_file_path = paths.target.replace("\\", "/").removeprefix("b/")
        if not current_file_path.lower().endswith(".codeunit.al") or current_file_path not in file_contents:
            continue

        current_codeunit_id = extract_codeunit_id_from_content(file_contents[current_file_path], current_file_path)
        found_test_attribute = False
        for line in diff_block.splitlines():
            if test_attribute_pattern.match(line):
                found_test_attribute = True
                continue
            if not found_test_attribute:
                continue
            procedure_match = procedure_pattern.match(line)
            if procedure_match:
                occurrences.append(TestOccurrence(codeunit_id=current_codeunit_id, function_name=procedure_match.group(1)))
                found_test_attribute = False
            elif not line.startswith("+"):
                found_test_attribute = False

    if not occurrences:
        raise NoTestsExtractedError
    return tuple(occurrences)


def normalize_test_occurrences(occurrences: Iterable[TestOccurrence]) -> list[TestEntry]:
    codeunit_functions: dict[int, set[str]] = {}
    for occurrence in occurrences:
        codeunit_functions.setdefault(occurrence.codeunit_id, set()).add(occurrence.function_name)
    return [TestEntry(codeunitID=codeunit_id, functionName=frozenset(function_names)) for codeunit_id, function_names in codeunit_functions.items()]


def extract_tests_from_patch(generated_patch: str, file_contents: dict[str, str]) -> list[TestEntry]:
    occurrences = extract_test_occurrences_from_patch(generated_patch, file_contents)
    return normalize_test_occurrences(occurrences)
