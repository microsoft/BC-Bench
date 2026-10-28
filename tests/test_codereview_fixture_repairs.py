import json
import subprocess

import pytest
from unidiff import PatchSet

from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.types import EvaluationCategory

_TELEMETRY = ("synthetic__privacy-009", "synthetic__privacy-clean-02")
_DISCOUNTS = ("synthetic__style-006", "synthetic__style-clean-04")
_RULES = ("synthetic__error-handling-assistedit-cancel-01", "synthetic__style-showmandatory-flowfield-01")
_REQUEST = "synthetic__style-this-keyword-01"
_CASES = (*_TELEMETRY, *_DISCOUNTS, *_RULES, _REQUEST)
_REQUEST_LABEL = "    var\n        UnexpectedRequestNoErr: Label 'Expected request number %1, but received %2.', Comment = '%1 = Expected request number, %2 = Actual request number';\n\n"


@pytest.fixture(scope="module")
def repaired_entries(before_fixture_repairs, tmp_path_factory):
    before = {e.instance_id: e for e in map(CodeReviewEntry.model_validate_json, before_fixture_repairs.splitlines())}
    after = {e.instance_id: e for e in CodeReviewEntry.load(EvaluationCategory.CODE_REVIEW.dataset_path)}
    materialized = {}
    for case in _CASES:
        versions = []
        for entry in (before[case], after[case]):
            repository = tmp_path_factory.mktemp(case)
            subprocess.run(["git", "init", "--quiet", str(repository)], capture_output=True, check=True)
            for option in ("--check", None):
                command = ["git", "-c", "core.autocrlf=false", "apply", *([option] if option else []), "-"]
                subprocess.run(command, cwd=repository, input=entry.patch.encode(), capture_output=True, check=True)
            sources = {}
            for block, file in zip(entry.patch.split("diff --git ")[1:], PatchSet(entry.patch), strict=True):
                assert file.is_added_file
                assert len(file) == 1
                assert file[0].source_length == 0
                assert file[0].target_start == 1
                lines = [line[1:] for line in block.splitlines(keepends=True) if line.startswith("+") and not line.startswith("+++ ")]
                assert file[0].target_length == len(lines) == file.added
                source = (repository / file.path).read_bytes()
                assert source == "".join(lines).encode()
                sources[file.path] = source.decode()
            versions.append(sources)
        materialized[case] = versions
    return before, after, materialized


def test_repairs_preserve_all_nonpatch_fields_and_unrelated_raw_rows(before_fixture_repairs, repaired_entries):
    before, after, _ = repaired_entries
    assert len(before) == len(after) == 145
    assert {case for case in before if before[case] != after[case]} == set(_CASES)
    original_rows = {json.loads(line)["instance_id"]: line for line in before_fixture_repairs.splitlines(keepends=True)}
    for line in EvaluationCategory.CODE_REVIEW.dataset_path.read_bytes().splitlines(keepends=True):
        entry = json.loads(line)
        case = entry["instance_id"]
        if case not in _CASES:
            assert line == original_rows[case]
        assert before[case].model_dump(exclude={"patch"}) == after[case].model_dump(exclude={"patch"})
        original = json.loads(original_rows[case])
        assert {k: v for k, v in original.items() if k != "patch"} == {k: v for k, v in entry.items() if k != "patch"}


@pytest.mark.parametrize("case", _CASES)
def test_only_the_approved_source_repair_is_present(repaired_entries, case):
    _, after, materialized = repaired_entries
    before, current = materialized[case]
    assert set(before) == set(current)
    expected = before.copy()
    if case in _TELEMETRY:
        path = "src/TaxDataMigrationHelper.Codeunit.al" if case == _TELEMETRY[0] else "src/BusinessSystemLogger.Codeunit.al"
        assert expected[path].count("Verbosity::Information") == 1
        expected[path] = expected[path].replace("Verbosity::Information", "Verbosity::Normal")
    elif case in _DISCOUNTS:
        path = "src/CleanFormatting.Codeunit.al"
        expected[path] = expected[path].replace('SalesLine."Line Discount %" := DiscountPct;', 'SalesLine.Validate("Line Discount %", DiscountPct);')
    elif case in _RULES:
        path = "src/SampleAEGenRule.Table.al" if case == _RULES[0] else "src/SampleQltyGenRule.Table.al"
        expected[path] = expected[path].replace(
            '        field(1; "Entry No."; Integer)\n        {\n',
            '        field(1; "Entry No."; Integer)\n        {\n            AutoIncrement = true;\n',
        )
    else:
        path = "src/DemoThisKeyword/DemoTestHelpers.Codeunit.al"
        expected[path] = expected[path].replace("    Subtype = Test;\n\n", "    Subtype = Test;\n\n" + _REQUEST_LABEL)
        expected[path] = expected[path].replace(
            "        No := CreateRequest();\n",
            "        No := CreateRequest();\n        if No <> 'DEMO001' then\n            Error(UnexpectedRequestNoErr, 'DEMO001', No);\n",
        )
    assert current == expected
    assert current != before
    for gold in after[case].expected_comments + after[case].ignored_comments:
        old_lines, new_lines = before[gold.file].splitlines(), current[gold.file].splitlines()
        assert new_lines[gold.line_start - 1 : gold.line_end or gold.line_start] == old_lines[gold.line_start - 1 : gold.line_end or gold.line_start]


@pytest.mark.parametrize("case", _DISCOUNTS)
def test_discount_validation_retains_clamping_modify_and_style_control(repaired_entries, case):
    _, _, materialized = repaired_entries
    source = materialized[case][1]["src/CleanFormatting.Codeunit.al"]
    assert (
        "        if DiscountPct <= 0 then\n            exit;\n\n"
        "        if DiscountPct > 100 then\n            DiscountPct := 100;\n\n"
        '        SalesLine.Validate("Line Discount %", DiscountPct);\n        SalesLine.Modify(true);'
    ) in source
    style = materialized[case][1]["src/BeginPlacementStyle.Codeunit.al"]
    if case == _DISCOUNTS[0]:
        assert "    if Amount > MaximumAmount then\n    begin\n" in style
    else:
        assert "    if Amount > MaximumAmount then\n      exit(MaximumAmount);" in style


@pytest.mark.parametrize("case", _RULES)
def test_generated_primary_key_retains_cancel_and_showmandatory_boundaries(repaired_entries, case):
    _, _, materialized = repaired_entries
    table_path = "src/SampleAEGenRule.Table.al" if case == _RULES[0] else "src/SampleQltyGenRule.Table.al"
    page_path = "src/SampleAEGenRules.Page.al" if case == _RULES[0] else "src/SampleQltyGenRules.Page.al"
    table, page = (materialized[case][1][path] for path in (table_path, page_path))
    assert table.count("AutoIncrement = true;") == 1
    assert 'key(PK; "Entry No.")' in table
    assert 'if Rec."Source Table No." = 0 then\n            Error(TableMissingErr);' in table
    assert 'if Page.RunModal(Page::"Objects", AllObjWithCaption) = Action::LookupOK then\n            Rec.Validate("Source Table No.", AllObjWithCaption."Object ID");' in table
    assert "FieldClass = FlowField;" in table
    assert "ShowMandatory" not in page
    if case == _RULES[0]:
        assert "DelayedInsert = true;" in page
        assert "Rec.HandleOnAssistEditSourceTable();\n                        CurrPage.SaveRecord();" in page
    else:
        assert "Rec.HandleOnAssistEditSourceTable();\n                        CurrPage.Update();" in page
        assert "CurrPage.SaveRecord" not in page


def test_request_assertion_checks_the_return_value_without_this_qualification(repaired_entries):
    _, _, materialized = repaired_entries
    source = materialized[_REQUEST][1]["src/DemoThisKeyword/DemoTestHelpers.Codeunit.al"]
    assert "        Initialize();\n        No := CreateRequest();\n        if No <> 'DEMO001' then\n            Error(UnexpectedRequestNoErr, 'DEMO001', No);" in source
    assert "        exit('DEMO001');" in source
    assert _REQUEST_LABEL in source
    assert "this." not in source
