import json
import re
import subprocess
from collections import Counter
from hashlib import sha256

import pytest
from bcbench_core.git import init_repo
from unidiff import PatchSet

from bcbench.dataset.codereview import CodeReviewEntry, ReviewCommentKind, Severity
from bcbench.types import EvaluationCategory

_RENAMES = {
    "error-handling-assistedit-cancel-01": {
        "src/SampleAssistEditGenRule.Table.al": "src/SampleAEGenRule.Table.al",
        "src/SampleAssistEditGenRules.Page.al": "src/SampleAEGenRules.Page.al",
    },
    "performance-015": {
        "src/ContactMgt.Codeunit.al": "src/ContactManagement.Codeunit.al",
        "src/InstallAppCZL.Codeunit.al": "src/InstallApplicationCZL.Codeunit.al",
        "src/ReservationMgt.Codeunit.al": "src/ReservationPriorityMgt.Codeunit.al",
    },
    "performance-017": {"src/AgentStatus.Table.al": "src/EAAgentStatus.Table.al"},
    "style-003": {"src/Page50200.ItemList.al": "src/ItemListExtension.Page.al"},
}
_RETIRED = {
    "error-clean-01": {0, 1, 2},
    "error-testfield-enabled-01": {1, 2},
    "perf-clean-01": {1, 2},
    "style-tooltip-mismatch-01": {1},
}
_TOOLTIPS = {
    ("error-clean-01", "src/DemoConfig/DemoConfigCard.Page.al"): [
        "Specifies the code that identifies this configuration record.",
        "Specifies a description to help identify this configuration record.",
        "Specifies when this configuration record was last inserted or modified on this page.",
    ],
    ("error-handling-errorinfo-actionable-boundary-01", "src/SyntheticSaveTarget.Page.al"): [
        "Specifies whether the selected target is an item or a stockkeeping unit.",
    ],
    ("error-testfield-enabled-01", "src/SampleWorkCenterCard.Page.al"): [
        "Specifies the number that identifies this work center.",
        "Specifies the vendor number used to filter purchase documents for this work center.",
    ],
    ("perf-clean-01", "src/DemoWhse/DemoOpenOrders.Page.al"): [
        "Specifies the number that identifies the order line.",
        "Specifies the processing state of the order line; this list shows open lines.",
    ],
    ("style-tooltip-mismatch-01", "src/DemoSpendCard/DemoSpendRequestCard.Page.al"): [
        "Specifies the number that identifies this spend request.",
    ],
}
_CAPTIONS = {
    ("accessibility-setselectionfilter-scope-01", "src/SyntheticSalesPlanningList.Page.al"): [("Create Orders", "Create orders")],
    ("performance-001", "src/SalesOrderCard.Page.al"): [("Refresh Totals", "Refresh totals")],
    ("style-010", "src/ServiceMgtSetup.Page.al"): [("Reset to Defaults", "Reset to defaults")],
    ("style-016", "src/WHTPstdPurchTaxCrMemos.Page.al"): [("Print Credit Memo", "Print credit memo"), ("Email Credit Memo", "Email credit memo")],
}
_TEMP = {
    ("privacy-006", "src/BusinessSystemLogger.Codeunit.al"): ("VendorBatch", "TempVendorBatch"),
    ("privacy-clean-02", "src/BusinessSystemLogger.Codeunit.al"): ("VendorBatch", "TempVendorBatch"),
    ("style-013", "src/CloudMigReplicateDataMgt.Codeunit.al"): ("TableList", "TempTableList"),
}
_TEST_TAGS = {
    ("style-013", "src/SCMSupplyPlanningIV.Codeunit.al"),
}
_CASE_MEMBERS = {
    "accessibility-setselectionfilter-scope-01": [0],
    "error-clean-01": [0, 1, 2],
    "error-handling-assistedit-cancel-01": [1, 2],
    "error-handling-errorinfo-actionable-boundary-01": [0],
    "error-testfield-enabled-01": [0, 1],
    "perf-clean-01": [4, 5],
    "performance-001": [1],
    "performance-004": [5],
    "performance-015": [3, 4, 5],
    "performance-017": [2],
    "performance-clean-01": [3, 4],
    "privacy-003": [3],
    "privacy-006": [2],
    "privacy-clean-02": [2],
    "security-005": [1],
    "security-016": [2],
    "style-003": [1],
    "style-010": [1],
    "style-013": [4, 5, 7],
    "style-016": [0, 1],
    "style-clean-02": [0],
    "style-tooltip-mismatch-01": [0],
    "upgrade-009": [6],
}


def _source_files(entry):
    sources = {}
    for file in PatchSet(entry.patch):
        source = ""
        for hunk in file:
            for line in hunk:
                if line.is_added or line.is_context:
                    source += line.value.replace("\r\n", "\n")
                elif line.line_type == "\\":
                    source = source.removesuffix("\n")
        sources[file.path] = source
    return sources


def _normalized(case, file, source):
    for text in _TOOLTIPS.get((case, file), []):
        source = re.sub(rf"^[ \t]*ToolTip = '{re.escape(text)}';\n", "", source, flags=re.MULTILINE)
    for old, new in _CAPTIONS.get((case, file), []):
        source = source.replace(f"Caption = '{new}';", f"Caption = '{old}';")
    if (case, file) in _TEMP:
        old, new = _TEMP[case, file]
        source = re.sub(rf"\b{new}\b", old, source)
    if case in {"performance-004", "performance-clean-01"} and file == "src/BatchModifier.Codeunit.al":
        source = re.sub(r"^[ \t]*// CORRECT:.*\n", "", source, flags=re.MULTILINE)
    if case == "privacy-003" and file == "src/CustomerEmailValidator.Codeunit.al":
        source = source.replace(", Comment = '%1 = Customer name, %2 = Email address'", "")
    if case == "security-005" and file == "src/BroadFinanceAccess.PermissionSet.al":
        source = source.replace("Caption = 'Broad Finance Access', Locked = true;", "Caption = 'Broad Finance Access';")
    if case == "security-016" and file == "src/ExpenseHtmlNotifier.Codeunit.al":
        source = source.replace("BodyTemplateLbl", "BodyTemplateTok")
        source = source.replace(", Comment = '%1 = Employee name, %2 = Expense description'", ", Locked = true")
    if case == "style-013" and file == "src/CustStPDFDocHandler.Codeunit.al":
        source = source.replace(
            "            Error(UnableToProcessDocumentErr, StatementGuid)\n        else\n            Error('Unable to create customer statement record for customer %1', CustomerNo);",
            "            Error(UnableToProcessDocumentErr, StatementGuid);\n        Error('Unable to create customer statement record for customer %1', CustomerNo);",
        )
    if (case, file) in _TEST_TAGS:
        source = re.sub(r"^[ \t]*// \[(?:FEATURE|SCENARIO|GIVEN|WHEN|THEN)\].*\n", "", source, flags=re.MULTILINE)
    if case == "style-clean-02" and file == "src/LineStartStyle.Codeunit.al":
        source = "\n".join(line.lstrip() for line in source.splitlines()) + "\n"
    if case == "upgrade-009" and file == "src/ContactSyncFolder.Table.al":
        source = source.replace("            DataClassification = EndUserIdentifiableInformation;\n", "")
    return source.rstrip("\r\n")


@pytest.fixture(scope="module")
def cleanup_entries():
    path = EvaluationCategory.CODE_REVIEW.dataset_path
    snapshot = path.parent.parent / "tests" / "fixtures" / "codereview-incidental-cleanup-baseline.jsonl"
    before = {entry.instance_id: entry for entry in CodeReviewEntry.load(snapshot)}
    after = {entry.instance_id: entry for entry in CodeReviewEntry.load(path)}
    assert set(before) == {"synthetic__" + case for case in _CASE_MEMBERS}
    return before, after


def test_cleanup_changes_only_the_authorized_cases_and_keeps_frozen_identity(cleanup_entries):
    before, after = cleanup_entries
    path = EvaluationCategory.CODE_REVIEW.dataset_path
    snapshot = path.parent.parent / "tests" / "fixtures" / "codereview-incidental-cleanup-baseline.jsonl"
    raw_before = {json.loads(line)["instance_id"]: line for line in snapshot.read_bytes().splitlines(keepends=True)}
    current_lines = path.read_bytes().splitlines(keepends=True)
    restored = b"".join(raw_before.get(json.loads(line)["instance_id"], line) for line in current_lines)
    assert sha256(restored).hexdigest() == "5bef88326e6467a0f4f5ad265a6fdbb2ce679bb795cacbf92d7b4aad17b5b348"
    assert len(before) == 23
    assert sum(map(len, _CASE_MEMBERS.values())) == 34
    assert len(after) == 145
    assert sum(len(entry.expected_comments) for entry in after.values()) == 299
    assert sum(len(entry.ignored_comments) for entry in after.values()) == 2

    def required(entries):
        return Counter(
            (entry.instance_id, gold.body, gold.severity, gold.kind)
            for entry in entries.values()
            for gold in entry.expected_comments
            if gold.kind == ReviewCommentKind.REVIEW_FINDING and gold.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
        )

    assert required(after) == required({**after, **before})
    assert sum(required(after).values()) == 225


@pytest.mark.parametrize("case", _CASE_MEMBERS)
def test_exact_patch_application_and_only_allowed_source_changes(cleanup_entries, tmp_path, case):
    before, after = cleanup_entries
    old, new = before["synthetic__" + case], after["synthetic__" + case]
    assert old.model_dump(exclude={"patch", "expected_comments", "ignored_comments"}) == new.model_dump(exclude={"patch", "expected_comments", "ignored_comments"})
    old_files = _source_files(old)
    new_files = _source_files(new)
    renamed = _RENAMES.get(case, {})
    assert set(new_files) == {renamed.get(file, file) for file in old_files}
    for file, source in old_files.items():
        assert _normalized(case, file, source) == _normalized(case, file, new_files[renamed.get(file, file)])
    init_repo(tmp_path)
    for option in ("--check", None):
        command = ["git", "apply", *([option] if option else []), "-"]
        subprocess.run(command, cwd=tmp_path, input=new.patch.encode("utf-8"), capture_output=True, check=True)
    for file in PatchSet(new.patch):
        assert file.is_added_file
        assert len(file) == 1
        assert file[0].source_length == 0
        assert file[0].target_start == 1
        assert file[0].target_length == len(new_files[file.path].splitlines())
        assert (tmp_path / file.path).read_text(encoding="utf-8") == new_files[file.path]


@pytest.mark.parametrize("case", _CASE_MEMBERS)
def test_gold_keeps_meaning_severity_kind_and_source_anchors(cleanup_entries, case):
    before, after = cleanup_entries
    old, new = before["synthetic__" + case], after["synthetic__" + case]
    old_files, new_files = _source_files(old), _source_files(new)
    for collection in ("expected_comments", "ignored_comments"):
        retired = _RETIRED.get(case, set()) if collection == "expected_comments" else ({0} if case == "style-tooltip-mismatch-01" else set())
        old_records = getattr(old, collection)
        for index in retired:
            assert old_records[index].kind == ReviewCommentKind.ANALYZER_DIAGNOSTIC
            assert old_records[index].diagnostic_id == "AA0218"
        retained = [gold for i, gold in enumerate(old_records) if i not in retired]
        for previous, current in zip(retained, getattr(new, collection), strict=True):
            assert previous.model_dump(exclude={"file", "line_start", "line_end"}) == current.model_dump(exclude={"file", "line_start", "line_end"})
            assert current.file == _RENAMES.get(case, {}).get(previous.file, previous.file)
            lines = new_files[current.file].splitlines()
            assert 1 <= current.line_start <= (current.line_end or current.line_start) <= len(lines)
            for old_line, new_line in ((previous.line_start, current.line_start), (previous.line_end, current.line_end)):
                if old_line is not None:
                    assert new_line is not None
                    left = old_files[previous.file].splitlines()[old_line - 1].strip()
                    right = lines[new_line - 1].strip()
                    assert _normalized(case, previous.file, left) == _normalized(case, previous.file, right)


def test_tooltip_cleanup_does_not_repair_the_misleading_close_action(cleanup_entries):
    _, after = cleanup_entries
    entry = after["synthetic__style-tooltip-mismatch-01"]
    assert len(entry.expected_comments) == 1
    assert entry.ignored_comments == []
    source = _source_files(entry)["src/DemoSpendCard/DemoSpendRequestCard.Page.al"]
    assert "Specifies the number that identifies this spend request." in source
    assert "ToolTip = 'Set the status field to Closed so that the request can be processed for approval.';" in source
    assert "Rec.Status := Rec.Status::Closed;" in source
    assert source.splitlines()[entry.expected_comments[0].line_start - 1].strip().startswith("ToolTip = 'Set the status")
    # The dedicated tooltip-boundary case remains a positive, not an incidental cleanup.
    assert len(after["synthetic__style-018"].expected_comments) == 1
    assert len(after["synthetic__style-018"].ignored_comments) == 1


def test_changes_are_present_not_just_accepted_by_normalization(cleanup_entries):
    _, after = cleanup_entries
    for (case, file), texts in _TOOLTIPS.items():
        source = _source_files(after["synthetic__" + case])[file]
        assert all(f"ToolTip = '{text}';" in source for text in texts)
    for (case, file), pairs in _CAPTIONS.items():
        source = _source_files(after["synthetic__" + case])[file]
        assert all(f"Caption = '{new}';" in source and f"Caption = '{old}';" not in source for old, new in pairs)
    for (case, file), (old, new) in _TEMP.items():
        source = _source_files(after["synthetic__" + case])[file]
        assert re.search(rf"\b{new}\b", source)
        assert not re.search(rf"\b{old}\b", source)
    for case, file in _TEST_TAGS:
        source = _source_files(after["synthetic__" + case])[file]
        assert all(source.count(f"// [{tag}]") == 1 for tag in ("FEATURE", "SCENARIO", "GIVEN", "WHEN", "THEN"))
        assert source.index("// [THEN]") < source.index("Assert.", source.index("// [THEN]"))
    assert "// CORRECT:" not in _source_files(after["synthetic__performance-clean-01"])["src/BatchModifier.Codeunit.al"]
    assert "// CORRECT: DeleteAll" not in _source_files(after["synthetic__performance-004"])["src/BatchModifier.Codeunit.al"]
    sources = _source_files(after["synthetic__style-013"])
    assert "Error(UnableToProcessDocumentErr, StatementGuid);\n        Error(" in sources["src/CustStPDFDocHandler.Codeunit.al"]
    assert "StatementGuid :=" not in sources["src/CustStPDFDocHandler.Codeunit.al"]
    assert "        try\n" in sources["src/CustStPDFDocHandler.Codeunit.al"]
    assert "        except\n" in sources["src/CustStPDFDocHandler.Codeunit.al"]
    source = _source_files(after["synthetic__style-clean-02"])["src/LineStartStyle.Codeunit.al"]
    assert "    local procedure SumRange" in source
    assert "        for Index := StartIndex to LimitCount do\n            Counter := Counter + Index;" in source
    source = _source_files(after["synthetic__privacy-003"])["src/CustomerEmailValidator.Codeunit.al"]
    assert "Comment = '%1 = Customer name, %2 = Email address'" in source
    assert "ErrorMessage := StrSubstNo(InvalidEmailErr, CustomerName, EmailAddress);" in source
    assert "Error(ErrorMessage);" in source
    source = _source_files(after["synthetic__security-005"])["src/BroadFinanceAccess.PermissionSet.al"]
    assert "Caption = 'Broad Finance Access';" in source
    assert "tabledata * = RIMD" in source
    assert "table * = X" in source
    source = _source_files(after["synthetic__security-016"])["src/ExpenseHtmlNotifier.Codeunit.al"]
    assert "BodyTemplateLbl: Label '<p>Dear %1,</p><p>%2</p>', Comment = '%1 = Employee name, %2 = Expense description';" in source
    assert "exit(StrSubstNo(BodyTemplateLbl, EmployeeName, Description));" in source
    source = _source_files(after["synthetic__upgrade-009"])["src/ContactSyncFolder.Table.al"]
    for number, name in ((16, "Created By"), (18, "Modified By")):
        field = source.split(f'field({number}; "{name}"; Code[50])', 1)[1].split("}", 1)[0]
        assert "DataClassification = EndUserIdentifiableInformation;" in field
        assert f'"{name}" := UserId;' in source
