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


@dataclass(frozen=True)
class _ALToken:
    kind: str
    value: str


def _tokenize_al(content: str) -> tuple[_ALToken, ...]:
    tokens: list[_ALToken] = []
    index = 0

    while index < len(content):
        character = content[index]
        next_character = content[index + 1] if index + 1 < len(content) else ""

        if character.isspace():
            index += 1
        elif character == "/" and next_character == "/":
            newline_index = content.find("\n", index + 2)
            index = len(content) if newline_index == -1 else newline_index + 1
        elif character == "/" and next_character == "*":
            comment_end = content.find("*/", index + 2)
            index = len(content) if comment_end == -1 else comment_end + 2
        elif character == "'":
            index += 1
            while index < len(content):
                if content[index] != "'":
                    index += 1
                elif index + 1 < len(content) and content[index + 1] == "'":
                    index += 2
                else:
                    index += 1
                    break
        elif character == '"':
            identifier: list[str] = []
            index += 1
            while index < len(content):
                if content[index] != '"':
                    identifier.append(content[index])
                    index += 1
                elif index + 1 < len(content) and content[index + 1] == '"':
                    identifier.append('"')
                    index += 2
                else:
                    index += 1
                    break
            tokens.append(_ALToken(kind="identifier", value="".join(identifier)))
        elif character.isalpha() or character == "_":
            identifier_end = index + 1
            while identifier_end < len(content) and (content[identifier_end].isalnum() or content[identifier_end] == "_"):
                identifier_end += 1
            tokens.append(_ALToken(kind="identifier", value=content[index:identifier_end]))
            index = identifier_end
        elif character.isdigit():
            number_end = index + 1
            while number_end < len(content) and content[number_end].isdigit():
                number_end += 1
            tokens.append(_ALToken(kind="number", value=content[index:number_end]))
            index = number_end
        else:
            tokens.append(_ALToken(kind="symbol", value=character))
            index += 1

    return tuple(tokens)


def _find_codeunit_id(tokens: tuple[_ALToken, ...], file_path: str) -> int:
    for index, token in enumerate(tokens[:-2]):
        id_token = tokens[index + 1]
        name_token = tokens[index + 2]
        if token.kind == "identifier" and token.value.casefold() == "codeunit" and id_token.kind == "number" and name_token.kind == "identifier":
            return int(id_token.value)
    raise TestExtractionError(f"No codeunit ID found in {file_path}")


def _find_test_procedure_names(tokens: tuple[_ALToken, ...]) -> tuple[str, ...]:
    function_names: list[str] = []
    found_test_attribute = False
    index = 0

    while index < len(tokens):
        if index + 2 < len(tokens) and tokens[index].value == "[" and tokens[index + 1].kind == "identifier" and tokens[index + 1].value.casefold() == "test" and tokens[index + 2].value == "]":
            found_test_attribute = True
            index += 3
            continue

        token = tokens[index]
        if token.kind == "identifier" and token.value.casefold() == "procedure":
            if index + 1 < len(tokens) and tokens[index + 1].kind == "identifier" and found_test_attribute:
                function_names.append(tokens[index + 1].value)
            found_test_attribute = False
        index += 1

    return tuple(function_names)


def extract_test_occurrences_from_content(content: str, file_path: str) -> tuple[TestOccurrence, ...]:
    tokens = _tokenize_al(content)
    function_names = _find_test_procedure_names(tokens)
    if not function_names:
        return ()

    codeunit_id = _find_codeunit_id(tokens, file_path)
    return tuple(TestOccurrence(codeunit_id=codeunit_id, function_name=function_name) for function_name in function_names)


def extract_codeunit_id_from_content(content: str, file_path: str) -> int:
    """Extract codeunit ID from AL file content.

    Args:
        content: The content of the AL file
        file_path: File path for error reporting

    Returns:
        Codeunit ID (always returns int, raises exception if not found)
    """
    return _find_codeunit_id(_tokenize_al(content), file_path)


def extract_test_occurrences_from_patch(generated_patch: str, file_contents: dict[str, str]) -> tuple[TestOccurrence, ...]:
    occurrences: list[TestOccurrence] = []
    procedure_pattern = re.compile(r"^\+\s*procedure\s+(\w+)\s*\(", flags=re.IGNORECASE)
    test_attribute_pattern = re.compile(r"^\+\s*\[Test\]", flags=re.IGNORECASE)

    for diff_block in split_git_diff_blocks(generated_patch):
        paths = extract_git_diff_paths(diff_block)
        if paths is None or paths.target == "/dev/null":
            continue

        current_file_path = paths.target.replace("\\", "/")
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
