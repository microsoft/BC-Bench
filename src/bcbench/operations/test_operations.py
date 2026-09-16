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
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _ALToken:
    kind: str
    value: str
    line: int


def _tokenize_al(content: str) -> tuple[_ALToken, ...]:
    tokens: list[_ALToken] = []
    index = 0
    line = 1

    while index < len(content):
        character = content[index]
        next_character = content[index + 1] if index + 1 < len(content) else ""

        if character.isspace():
            if character == "\n":
                line += 1
            index += 1
        elif character == "/" and next_character == "/":
            newline_index = content.find("\n", index + 2)
            index = len(content) if newline_index == -1 else newline_index
        elif character == "/" and next_character == "*":
            comment_end = content.find("*/", index + 2)
            token_end = len(content) if comment_end == -1 else comment_end + 2
            line += content[index:token_end].count("\n")
            index = token_end
        elif character == "'":
            index += 1
            while index < len(content):
                if content[index] == "\n":
                    line += 1
                    index += 1
                elif content[index] != "'":
                    index += 1
                elif index + 1 < len(content) and content[index + 1] == "'":
                    index += 2
                else:
                    index += 1
                    break
        elif character == '"':
            identifier: list[str] = []
            token_line = line
            index += 1
            while index < len(content):
                if content[index] == "\n":
                    identifier.append(content[index])
                    line += 1
                    index += 1
                elif content[index] != '"':
                    identifier.append(content[index])
                    index += 1
                elif index + 1 < len(content) and content[index + 1] == '"':
                    identifier.append('"')
                    index += 2
                else:
                    index += 1
                    break
            tokens.append(_ALToken(kind="quoted_identifier", value="".join(identifier), line=token_line))
        elif character.isalpha() or character == "_":
            identifier_end = index + 1
            while identifier_end < len(content) and (content[identifier_end].isalnum() or content[identifier_end] == "_"):
                identifier_end += 1
            tokens.append(_ALToken(kind="identifier", value=content[index:identifier_end], line=line))
            index = identifier_end
        elif character.isdigit():
            number_end = index + 1
            while number_end < len(content) and content[number_end].isdigit():
                number_end += 1
            tokens.append(_ALToken(kind="number", value=content[index:number_end], line=line))
            index = number_end
        else:
            tokens.append(_ALToken(kind="symbol", value=character, line=line))
            index += 1

    return tuple(tokens)


def _is_identifier(token: _ALToken) -> bool:
    return token.kind in {"identifier", "quoted_identifier"}


def _is_keyword(token: _ALToken, keyword: str) -> bool:
    return token.kind == "identifier" and token.value.casefold() == keyword


def _find_codeunit_id(tokens: tuple[_ALToken, ...], file_path: str) -> int:
    for index, token in enumerate(tokens[:-2]):
        id_token = tokens[index + 1]
        name_token = tokens[index + 2]
        if _is_keyword(token, "codeunit") and id_token.kind == "number" and _is_identifier(name_token):
            return int(id_token.value)
    raise TestExtractionError(f"No codeunit ID found in {file_path}")


def _find_attribute_end(tokens: tuple[_ALToken, ...], start_index: int) -> int | None:
    bracket_depth = 0
    for index in range(start_index, len(tokens)):
        if tokens[index].value == "[":
            bracket_depth += 1
        elif tokens[index].value == "]":
            bracket_depth -= 1
            if bracket_depth == 0:
                return index
    return None


def _find_procedure_end(tokens: tuple[_ALToken, ...], procedure_index: int) -> int | None:
    body_start = None
    for index in range(procedure_index + 2, len(tokens)):
        if _is_keyword(tokens[index], "procedure"):
            return None
        if _is_keyword(tokens[index], "begin"):
            body_start = index
            break
    if body_start is None:
        return None

    block_stack = ["begin"]
    for index in range(body_start + 1, len(tokens)):
        token = tokens[index]
        if token.kind != "identifier":
            continue

        keyword = token.value.casefold()
        if keyword in {"begin", "case", "repeat"}:
            block_stack.append(keyword)
        elif (keyword == "end" and block_stack[-1] in {"begin", "case"}) or (keyword == "until" and block_stack[-1] == "repeat"):
            block_stack.pop()

        if not block_stack:
            semicolon_index = index + 1
            if semicolon_index < len(tokens) and tokens[semicolon_index].value == ";":
                return semicolon_index
            return index
    return None


def _find_test_procedures(tokens: tuple[_ALToken, ...]) -> tuple[tuple[str, int, int], ...]:
    procedures: list[tuple[str, int, int]] = []
    attribute_start_line: int | None = None
    has_test_attribute = False
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.value == "[":
            attribute_end = _find_attribute_end(tokens, index)
            if attribute_end is None:
                break
            attribute_start_line = token.line if attribute_start_line is None else attribute_start_line
            if index + 1 < attribute_end and _is_keyword(tokens[index + 1], "test"):
                has_test_attribute = True
            index = attribute_end + 1
            continue

        if _is_keyword(token, "procedure"):
            name_index = index + 1
            procedure_end = _find_procedure_end(tokens, index)
            if has_test_attribute and attribute_start_line is not None and name_index < len(tokens) and _is_identifier(tokens[name_index]) and procedure_end is not None:
                procedures.append((tokens[name_index].value, attribute_start_line, tokens[procedure_end].line))
            attribute_start_line = None
            has_test_attribute = False
            index = procedure_end + 1 if procedure_end is not None else index + 1
            continue

        if attribute_start_line is not None and not (_is_keyword(token, "local") or _is_keyword(token, "internal")):
            attribute_start_line = None
            has_test_attribute = False
        index += 1

    return tuple(procedures)


def extract_test_occurrences_from_content(content: str, file_path: str) -> tuple[TestOccurrence, ...]:
    tokens = _tokenize_al(content)
    procedures = _find_test_procedures(tokens)
    if not procedures:
        return ()

    codeunit_id = _find_codeunit_id(tokens, file_path)
    return tuple(TestOccurrence(codeunit_id=codeunit_id, function_name=function_name, start_line=start_line, end_line=end_line) for function_name, start_line, end_line in procedures)


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
    hunk_pattern = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for diff_block in split_git_diff_blocks(generated_patch):
        paths = extract_git_diff_paths(diff_block)
        if paths is None or paths.target == "/dev/null":
            continue

        current_file_path = paths.target.replace("\\", "/")
        if not current_file_path.lower().endswith(".codeunit.al") or current_file_path not in file_contents:
            continue

        current_codeunit_id = extract_codeunit_id_from_content(file_contents[current_file_path], current_file_path)
        found_test_attribute = False
        attribute_start_line: int | None = None
        target_line: int | None = None
        for line in diff_block.splitlines():
            hunk_match = hunk_pattern.match(line)
            if hunk_match:
                target_line = int(hunk_match.group(1))
                continue

            if test_attribute_pattern.match(line):
                found_test_attribute = True
                attribute_start_line = target_line
            elif found_test_attribute:
                procedure_match = procedure_pattern.match(line)
                if procedure_match and attribute_start_line is not None and target_line is not None:
                    occurrences.append(
                        TestOccurrence(
                            codeunit_id=current_codeunit_id,
                            function_name=procedure_match.group(1),
                            start_line=attribute_start_line,
                            end_line=target_line,
                        )
                    )
                    found_test_attribute = False
                    attribute_start_line = None
                elif not line.startswith("+"):
                    found_test_attribute = False
                    attribute_start_line = None

            if target_line is not None and (line.startswith("+") or not line.startswith("-")):
                target_line += 1

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
