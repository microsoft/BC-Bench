import re

from bcbench.dataset import TestEntry
from bcbench.exceptions import NoTestsExtractedError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def extract_codeunit_id_from_content(content: str, file_path: str) -> int:
    """Extract codeunit ID from AL file content.

    Args:
        content: The content of the AL file
        file_path: File path for error reporting

    Returns:
        Codeunit ID (always returns int, raises exception if not found)
    """
    codeunit_pattern = r'codeunit\s+(\d+)\s+"[^"]*"'
    match = re.search(codeunit_pattern, content)
    if match:
        return int(match.group(1))
    raise ValueError(f"No codeunit ID found in {file_path}")


def extract_tests_from_patch(generated_patch: str, file_contents: dict[str, str]) -> list[TestEntry]:
    """Extract test entries from an AL code patch by finding NEW test procedures.

    Args:
        generated_patch: A git diff patch containing AL code with test procedures
        file_contents: Dict mapping file paths to their content

    Returns:
        List of TestEntry dicts with codeunitID and functionName

    Raises:
        NoTestsExtractedError: If no test entries are found in the patch
    """
    test_entries: list[TestEntry] = []
    current_codeunit_id: int | None = None

    # Pattern to match test procedure declarations that are ADDED (have + marker)
    procedure_pattern = r"^\+\s*procedure\s+(\w+)\s*\("

    # Pattern to match [Test] attribute that is ADDED (have + marker)
    test_attribute_pattern = r"^\+\s*\[Test\]"

    # Pattern to match diff file headers: diff --git a/<path> b/<path>
    file_header_pattern = r"^diff --git a/(.+) b/(.+)$"

    lines = generated_patch.split("\n")
    found_test_attribute = False

    for line in lines:
        file_header_match = re.match(file_header_pattern, line)
        if file_header_match:
            current_file_path = file_header_match.group(2)
            # Only process codeunit files (*.Codeunit.al, case-insensitive)
            if current_file_path and current_file_path.lower().endswith(".codeunit.al"):
                if current_file_path in file_contents:
                    content = file_contents[current_file_path]
                    current_codeunit_id = extract_codeunit_id_from_content(content, current_file_path)
            else:
                # Reset codeunit ID for non-codeunit files
                current_codeunit_id = None

            continue

        if re.match(test_attribute_pattern, line):
            found_test_attribute = True
            continue

        if found_test_attribute and current_codeunit_id is not None:
            procedure_match = re.match(procedure_pattern, line)
            if procedure_match:
                function_name = procedure_match.group(1)

                existing_entry = None
                for entry in test_entries:
                    if entry.codeunitID == current_codeunit_id:
                        existing_entry = entry
                        break

                if existing_entry:
                    if function_name not in existing_entry.functionName:
                        existing_entry.functionName.add(function_name)
                else:
                    test_entries.append(TestEntry(codeunitID=current_codeunit_id, functionName={function_name}))

                found_test_attribute = False
            elif not line.startswith("+"):
                found_test_attribute = False

    if not test_entries:
        raise NoTestsExtractedError()

    return test_entries
