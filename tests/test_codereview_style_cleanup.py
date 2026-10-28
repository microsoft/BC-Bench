import json
import re
import subprocess
from hashlib import sha256

import pytest
from unidiff import PatchSet

from bcbench.dataset.codereview import CodeReviewEntry, ReviewCommentKind, Severity

_RENAMES = {
    "performance-001": {
        "src/FADepreciationBook.Table.al": "src/FADepreciationBookFP.Table.al",
        "src/SalesOrderCard.Page.al": "src/SalesOrderCardFP.Page.al",
    },
    "performance-004": {"src/BatchModifier.Codeunit.al": "src/BatchModifierFP.Codeunit.al"},
    "performance-018": {
        "src/BOMBufferMgt.Codeunit.al": "src/BOMBufferManagement.Codeunit.al",
        "src/PurchRcptLineMgt.Codeunit.al": "src/PurchRcptLineMgmt.Codeunit.al",
    },
    "performance-020": {"src/AssemblyOrderSubform.Page.al": "src/AssemblyOrderSubformSample.Page.al"},
    "performance-022": {
        "src/AssemblyLineMgt.Codeunit.al": "src/AssemblyLineCheck.Codeunit.al",
        "src/PurchAllocAccMgt.Codeunit.al": "src/PurchaseAllocAccMgt.Codeunit.al",
        "src/SKUMgt.Codeunit.al": "src/SKUManagement.Codeunit.al",
    },
    "performance-clean-01": {"src/BatchModifier.Codeunit.al": "src/BatchModifierFP.Codeunit.al"},
    "style-008": {"src/CustomerIntegrationSetup.table.al": "src/CustomerIntegrationSetup.Table.al"},
    "style-009": {"src/CleanOtherStyle.Page.al": "src/CustomerDetailCard.Page.al"},
    "style-010": {"src/ServiceMgtSetup.Page.al": "src/SyntheticServiceMgtSetup.Page.al"},
    "upgrade-obsolete-caption-01": {"src/SampleSubcWorkCenterCard.Page.al": "src/SampleWorkCenterCard.Page.al"},
}
_DELETED_COMMENTS = {
    ("performance-001", "src/FADepreciationBook.Table.al"): {46, 47},
    ("performance-001", "src/SalesOrderCard.Page.al"): {59, 71, 72, 75, 76, 83},
    ("performance-002", "src/SetupReader.Codeunit.al"): {44, 45, 56, 64},
    ("performance-002", "src/TempBufferProcessor.Codeunit.al"): {9, 10, 16, 17, 18, 19, 23, 36, 51},
    ("performance-018", "src/BOMBufferMgt.Codeunit.al"): {11, 15, 24, 33, 38},
    ("performance-018", "src/CustomReportLayoutsList.Page.al"): {60, 65, 71},
    ("performance-018", "src/PurchRcptLineMgt.Codeunit.al"): {10, 14, 32, 37, 53},
    ("performance-020", "src/ItemLedgerEntryAPAC.Table.al"): {128},
    ("performance-022", "src/PurchAllocAccMgt.Codeunit.al"): {15, 19, 22, 25, 46},
    ("style-011", "src/AgentTaskTemplate.Codeunit.al"): {35},
    ("upgrade-009", "src/UpgradeExpenseAgentSetup.Codeunit.al"): {75, 102},
}
_TRAILING_COMMENTS = {
    ("style-011", "src/AgentTaskTemplate.Codeunit.al"): {34: "// begin keyword at line 78 - but more variables after"},
    ("style-011", "src/NonDeductiblePurchPosting.Codeunit.al"): {28: "// Unnecessary BEGIN..END for compound statement"},
    ("style-011", "src/PayablesAgent.Codeunit.al"): {19: "// BEGIN..END for single statement"},
}
_SPLIT_CASE = "style-tooltip-mismatch-01"
_TABLE = "src/DemoSpendCard/DemoSpendRequest.Table.al"
_ENUM = "src/DemoSpendCard/DemoSpendRequestStatus.Enum.al"
_CASES = sorted(set(_RENAMES) | {case for case, _ in _DELETED_COMMENTS} | {_SPLIT_CASE})


def _sources(entry):
    sources = {}
    for file in PatchSet(entry.patch):
        assert file.is_added_file
        assert len(file) == 1
        hunk = file[0]
        assert hunk.source_length == 0
        assert hunk.target_start == 1
        lines = [line.value for line in hunk if line.is_added]
        assert len(lines) == hunk.target_length
        raw = "".join(lines).encode("utf-8")
        if any(line.line_type == "\\" for line in hunk):
            raw = raw.removesuffix(b"\n")
        sources[file.path] = raw
    return sources


def _expected_files(case, sources):
    expected, anchors = {}, {}
    for file, raw in sources.items():
        target = _RENAMES.get(case, {}).get(file, file)
        lines = raw.splitlines(keepends=True)
        if case == _SPLIT_CASE and file == _TABLE:
            assert lines[25].strip() == b""
            expected[_TABLE] = b"".join(lines[:25])
            expected[_ENUM] = b"".join(lines[26:])
            for number in range(1, 26):
                anchors[(file, number)] = (_TABLE, number)
            for number in range(27, 34):
                anchors[(file, number)] = (_ENUM, number - 26)
            continue
        kept = []
        for number, line in enumerate(lines, 1):
            if number in _DELETED_COMMENTS.get((case, file), set()):
                assert line.lstrip().startswith(b"//")
                assert not line.lstrip().startswith(b"///")
                continue
            retained = line
            suffix = _TRAILING_COMMENTS.get((case, file), {}).get(number)
            if suffix:
                content = line.rstrip(b"\r\n")
                assert content.endswith(suffix.encode())
                assert content.split(b"//")[0].strip() == b"begin"
                retained = content.removesuffix(suffix.encode()).rstrip() + line[len(content) :]
            kept.append(retained)
            anchors[(file, number)] = (target, len(kept))
        expected[target] = b"".join(kept)
    return expected, anchors


@pytest.fixture(scope="module")
def style_cleanup_entries(before_style_cleanup, before_fixture_repairs):
    before = {e.instance_id: e for e in map(CodeReviewEntry.model_validate_json, before_style_cleanup.splitlines())}
    after = {e.instance_id: e for e in map(CodeReviewEntry.model_validate_json, before_fixture_repairs.splitlines())}
    return before, after


def test_style_cleanup_scope_and_frozen_identity(before_style_cleanup, before_fixture_repairs, style_cleanup_entries):
    before, after = style_cleanup_entries
    assert sha256(before_style_cleanup).hexdigest() == "2499ef2792e99b7c02b983da5cd0c3810158968767b16705ec35a2338e5a844f"
    assert len(_CASES) == 14
    assert sum(map(len, _RENAMES.values())) == 14
    assert sum(map(len, _DELETED_COMMENTS.values())) == 43
    assert sum(map(len, _TRAILING_COMMENTS.values())) == 3
    assert set(before) == set(after)
    assert len(after) == 145
    assert {key for key in before if before[key] != after[key]} == {"synthetic__" + case for case in _CASES}
    assert sum(len(e.expected_comments) for e in after.values()) == 299
    assert sum(len(e.ignored_comments) for e in after.values()) == 2
    assert (
        sum(gold.kind == ReviewCommentKind.REVIEW_FINDING and gold.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL) for entry in after.values() for gold in entry.expected_comments)
        == 225
    )
    assert before["synthetic__style-015"] == after["synthetic__style-015"]
    original_rows = {json.loads(line)["instance_id"]: line for line in before_style_cleanup.splitlines(keepends=True)}
    for line in before_fixture_repairs.splitlines(keepends=True):
        current = json.loads(line)
        original = json.loads(original_rows[current["instance_id"]])
        if current["instance_id"] not in {"synthetic__" + case for case in _CASES}:
            assert line == original_rows[current["instance_id"]]
        for field in ("patch", "expected_comments", "ignored_comments"):
            original.pop(field, None)
            current.pop(field, None)
        assert original == current


@pytest.mark.parametrize("case", _CASES)
def test_only_authorized_source_changes_and_exact_gold_mapping(style_cleanup_entries, case):
    before, after = style_cleanup_entries
    old, new = before["synthetic__" + case], after["synthetic__" + case]
    assert old.model_dump(exclude={"patch", "expected_comments", "ignored_comments"}) == new.model_dump(exclude={"patch", "expected_comments", "ignored_comments"})
    old_sources, new_sources = _sources(old), _sources(new)
    expected, anchors = _expected_files(case, old_sources)
    assert new_sources == expected
    assert len({path.casefold() for path in new_sources}) == len(new_sources)
    for previous, current in zip(old.expected_comments + old.ignored_comments, new.expected_comments + new.ignored_comments, strict=True):
        assert previous.model_dump(exclude={"file", "line_start", "line_end"}) == current.model_dump(exclude={"file", "line_start", "line_end"})
        assert (current.file, current.line_start) == anchors[(previous.file, previous.line_start)]
        if previous.line_end is not None:
            assert (current.file, current.line_end) == anchors[(previous.file, previous.line_end)]
        else:
            assert current.line_end is None
    for file, target in _RENAMES.get(case, {}).items():
        declaration = old_sources[file].decode("utf-8").splitlines()[0]
        match = re.fullmatch(r'(table|page|codeunit) \d+ "([^"]+)"', declaration)
        assert match is not None
        assert target.rsplit("/", 1)[1] == re.sub(r"[ .]", "", match[2]) + "." + match[1].title() + ".al"
        assert file not in new_sources
    if case == _SPLIT_CASE:
        assert new_sources[_ENUM] == b"".join(old_sources[_TABLE].splitlines(keepends=True)[26:])
        assert b'enum 50132 "Demo Spend Request Status"' in new_sources[_ENUM]
        assert b"Extensible = false;" in new_sources[_ENUM]
        assert b"value(0; Open)" in new_sources[_ENUM]
        assert b"value(1; Closed)" in new_sources[_ENUM]
        page = "src/DemoSpendCard/DemoSpendRequestCard.Page.al"
        assert new_sources[page] == old_sources[page]


@pytest.mark.parametrize("case", _CASES)
def test_style_cleanup_patch_applies_with_exact_path_case_and_bytes(style_cleanup_entries, tmp_path, case):
    _, after = style_cleanup_entries
    entry = after["synthetic__" + case]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    for option in ("--check", None):
        command = ["git", "-c", "core.autocrlf=false", "apply", *([option] if option else []), "-"]
        subprocess.run(command, cwd=tmp_path, input=entry.patch.encode(), check=True, capture_output=True)
    expected = _sources(entry)
    actual = {file.relative_to(tmp_path).as_posix(): file.read_bytes() for file in (tmp_path / "src").rglob("*") if file.is_file()}
    assert actual == expected
