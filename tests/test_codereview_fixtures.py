import json
import re
import subprocess
from collections import Counter
from hashlib import sha256

import pytest
from bcbench_core.git import apply_patch, init_repo
from unidiff import PatchSet

from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment, ReviewCommentKind, Severity
from bcbench.types import EvaluationCategory

_SCAN = "synthetic__performance-014"
_API = "synthetic__performance-009"
_GROUPS = "synthetic__error-handling-drilldown-position-01"
_BULK = "synthetic__performance-010"
_INTERNAL = "synthetic__security-014"
_RELATION = "synthetic__data-modeling-tablerelation-restriction-mismatch-01"
_NOTICE = "synthetic__style-012"
_STATEMENT = "synthetic__style-013"
_NOTE_TOOLTIP = "synthetic__style-018"
_CLOSE_TOOLTIP = "synthetic__style-tooltip-mismatch-01"
_COST_BASIS = "synthetic__performance-018"
_VENDOR_REPORT = "synthetic__performance-023"
_PENDING_CRM = "synthetic__privacy-010"
_HTTP_LOCKS = "synthetic__privacy-015"
_RESET = "synthetic__style-010"
_FIRST_GOLD_BATCH = (_COST_BASIS, _VENDOR_REPORT, _PENDING_CRM, _HTTP_LOCKS, _RESET)
_ENTRY_IDS = (_SCAN, _API, _GROUPS, _BULK, _INTERNAL, _RELATION, _NOTICE, _STATEMENT, _NOTE_TOOLTIP, _CLOSE_TOOLTIP, *_FIRST_GOLD_BATCH)
_TOOLTIP_ALIAS_BODY = (
    "This exact source field and its bound page control both lack tooltip text. Add the effective tooltip on either declaration. "
    "This is an alternative anchor for the existing AA0218 neutral issue, not a second required issue."
)
_TOOLTIP_ALIASES = {
    _NOTE_TOOLTIP: ReviewComment(
        file="src/SampleNoteExt.TableExt.al",
        line_start=5,
        line_end=5,
        severity=Severity.MEDIUM,
        domain="ui",
        body=_TOOLTIP_ALIAS_BODY,
        articles=["ui/bound-page-field-inherits-source-field-tooltip"],
        kind=ReviewCommentKind.ANALYZER_DIAGNOSTIC,
        diagnostic_id="AA0218",
    ),
    _CLOSE_TOOLTIP: ReviewComment(
        file="src/DemoSpendCard/DemoSpendRequest.Table.al",
        line_start=8,
        line_end=8,
        severity=Severity.MEDIUM,
        domain="ui",
        body=_TOOLTIP_ALIAS_BODY,
        kind=ReviewCommentKind.ANALYZER_DIAGNOSTIC,
        diagnostic_id="AA0218",
    ),
}


def _unique_object(pairs):
    assert len(dict(pairs)) == len(pairs), "Duplicate JSON object keys"
    return dict(pairs)


@pytest.fixture(scope="module")
def before_incidental_cleanup():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    snapshot = dataset.parent.parent / "tests" / "fixtures" / "codereview-incidental-cleanup-baseline.jsonl"
    frozen = {json.loads(line)["instance_id"]: line for line in snapshot.read_bytes().splitlines(keepends=True)}
    assert len(frozen) == 23
    restored = b"".join(frozen.get(json.loads(line)["instance_id"], line) for line in dataset.read_bytes().splitlines(keepends=True))
    assert sha256(restored).hexdigest() == "5bef88326e6467a0f4f5ad265a6fdbb2ce679bb795cacbf92d7b4aad17b5b348"
    return restored


@pytest.fixture(scope="module")
def before_first_gold_batch(before_incidental_cleanup):
    # Restore only this batch's five repaired records and two aliases, not the audit artifacts.
    snapshot = EvaluationCategory.CODE_REVIEW.dataset_path.parent.parent / "tests" / "fixtures" / "codereview-first-gold-batch-baseline.jsonl"
    frozen = {json.loads(line)["instance_id"]: line for line in snapshot.read_bytes().splitlines(keepends=True)}
    assert set(frozen) == set(_FIRST_GOLD_BATCH)
    lines = before_incidental_cleanup.splitlines(keepends=True)
    seen = set()
    for index, line in enumerate(lines):
        entry = json.loads(line, object_pairs_hook=_unique_object)
        entry_id = entry["instance_id"]
        assert entry_id not in seen
        seen.add(entry_id)
        if entry_id in frozen:
            lines[index] = frozen[entry_id]
        elif entry_id in _TOOLTIP_ALIASES:
            assert [ReviewComment.model_validate(comment) for comment in entry.pop("ignored_comments")] == [_TOOLTIP_ALIASES[entry_id]]
            lines[index] = (json.dumps(entry, ensure_ascii=False) + "\n").encode()
    assert len(seen) == 145
    assert _TOOLTIP_ALIASES.keys() <= seen
    restored = b"".join(lines)
    assert sha256(restored).hexdigest() == "42178a85e9e8ce023f32ef030a95f2c2829f76268d47cac47c8beafd577a8a30"
    return restored


@pytest.fixture(scope="module")
def frozen_gold_entries(before_first_gold_batch):
    return {entry.instance_id: entry for entry in (CodeReviewEntry.model_validate_json(line) for line in before_first_gold_batch.splitlines())}


@pytest.fixture(scope="module")
def materialized_entries(tmp_path_factory):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(dataset)}
    raw_entries = {json.loads(line)["instance_id"]: line for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()}
    materialized = {}
    for entry_id in _ENTRY_IDS:
        raw = json.loads(raw_entries[entry_id], object_pairs_hook=_unique_object)
        entry = entries[entry_id]
        assert raw["expect_findings"] is any(gold.kind == ReviewCommentKind.REVIEW_FINDING for gold in entry.expected_comments)
        repo = tmp_path_factory.mktemp(entry_id)
        init_repo(repo)
        subprocess.run(["git", "apply", "--check", "-"], cwd=repo, input=entry.patch, text=True, encoding="utf-8", capture_output=True, check=True)
        apply_patch(repo, entry.patch, entry_id)

        files = {}
        blocks = entry.patch.split("diff --git ")[1:]
        patch_set = PatchSet(entry.patch)
        assert len(blocks) == len(patch_set)
        for block, patched_file in zip(blocks, patch_set, strict=True):
            assert patched_file.is_added_file
            assert len(patched_file) == 1
            hunk = patched_file[0]
            # Parsers and git apply can silently ignore additions beyond a short hunk.
            raw_lines = [line[1:] for line in block.splitlines() if line.startswith("+") and not line.startswith("+++ ")]
            assert hunk.source_length == 0
            assert hunk.target_start == 1
            assert hunk.target_length == len(raw_lines) == patched_file.added
            source = (repo / patched_file.path).read_text(encoding="utf-8")
            assert source == "\n".join(raw_lines) + "\n"
            assert source.rstrip().endswith("}")
            assert source.count("{") == source.count("}")
            files[patched_file.path] = source

        for comment in entry.expected_comments + entry.ignored_comments:
            lines = files[comment.file].splitlines()
            assert 1 <= comment.line_start <= (comment.line_end or comment.line_start) <= len(lines)
        materialized[entry_id] = entry, files
    return materialized


@pytest.mark.parametrize(
    ("entry_id", "page_index", "table_declaration", "page_declaration"),
    [
        (_NOTE_TOOLTIP, 0, 'field(50120; "Sample Note"; Text[50])', 'field(SampleNote; Rec."Sample Note")'),
    ],
)
def test_table_tooltip_alias_is_neutral_for_the_exact_existing_page_binding(materialized_entries, before_first_gold_batch, entry_id, page_index, table_declaration, page_declaration):
    entry, files = materialized_entries[entry_id]
    alias = _TOOLTIP_ALIASES[entry_id]
    assert entry.ignored_comments == [alias]
    assert entry.environment_setup_version == "27.0"
    page_gold = entry.expected_comments[page_index]
    assert len(entry.expected_comments) == page_index + 1
    assert page_gold.kind == alias.kind == ReviewCommentKind.ANALYZER_DIAGNOSTIC
    assert page_gold.diagnostic_id == alias.diagnostic_id == "AA0218"
    assert page_gold.file != alias.file
    assert page_gold.articles == alias.articles
    for gold, declaration in ((alias, table_declaration), (page_gold, page_declaration)):
        lines = files[gold.file].splitlines()
        assert lines[gold.line_start - 1].strip() == declaration
        field_body = "\n".join(lines[gold.line_start :]).split("}", 1)[0]
        assert "ToolTip" not in field_body

    if entry_id == _NOTE_TOOLTIP:
        page = files[page_gold.file]
        assert 'field(No; Rec."No.")' in page
        assert "field(Name; Rec.Name)" in page
        assert not any(gold.kind == ReviewCommentKind.REVIEW_FINDING for gold in entry.expected_comments)
    else:
        close_gold = entry.expected_comments[0]
        assert close_gold.kind == ReviewCommentKind.REVIEW_FINDING
        assert close_gold.severity == Severity.MEDIUM
        assert close_gold.line_start == 27
        assert "processed for approval" in close_gold.body
        assert "Rec.Status := Rec.Status::Closed;" in files[close_gold.file]


@pytest.mark.parametrize(("entry_id", "addition_count"), [(_COST_BASIS, 1), (_VENDOR_REPORT, 1), (_PENDING_CRM, 1), (_HTTP_LOCKS, 3), (_RESET, 1)])
def test_first_gold_batch_preserves_existing_gold_and_reanchors_without_changing_meaning(materialized_entries, frozen_gold_entries, entry_id, addition_count):
    entry, files = materialized_entries[entry_id]
    original = frozen_gold_entries[entry_id]
    assert entry.model_dump(exclude={"patch", "expected_comments"}) == original.model_dump(exclude={"patch", "expected_comments"})
    assert len(entry.expected_comments) == len(original.expected_comments) + addition_count
    old_sources = {file.path: {line.target_line_no: line.value.rstrip("\r\n") for hunk in file for line in hunk if not line.is_removed} for file in PatchSet(original.patch)}
    for before, after in zip(original.expected_comments, entry.expected_comments[: len(original.expected_comments)], strict=True):
        assert before.model_dump(exclude={"line_start", "line_end"}) == after.model_dump(exclude={"line_start", "line_end"})
        for old_line, new_line in ((before.line_start, after.line_start), (before.line_end, after.line_end)):
            if old_line is not None:
                assert new_line is not None
                assert old_sources[before.file][old_line] == files[after.file].splitlines()[new_line - 1]
    for gold in entry.expected_comments[len(original.expected_comments) :]:
        assert gold.kind == ReviewCommentKind.REVIEW_FINDING
        assert gold.severity in (Severity.MEDIUM, Severity.HIGH)
        assert gold.articles == []


@pytest.mark.parametrize("entry_id", _FIRST_GOLD_BATCH)
def test_first_gold_batch_repairs_only_explicit_target_compatibility_blockers(materialized_entries, frozen_gold_entries, entry_id):
    _, files = materialized_entries[entry_id]
    replacements = {
        _COST_BASIS: {
            "src/BOMBufferMgt.Codeunit.al": [("BOMBuffer.Quantity", 'BOMBuffer."Qty. per BOM Line"')],
            "src/CustomReportLayoutsList.Page.al": [
                ('    CardPageId = "Custom Report Layout";\n', ""),
                ('Rec."Layout Format"', "Rec.Type"),
                ("Rec.\"Last Modified by User\" <> ''", "not IsNullGuid(Rec.SystemModifiedBy)"),
                ('User.Get(Rec."Last Modified by User")', "User.Get(Rec.SystemModifiedBy)"),
                ("Rec.\"Created by User\" <> ''", "not IsNullGuid(Rec.SystemCreatedBy)"),
                ('User.Get(Rec."Created by User")', "User.Get(Rec.SystemCreatedBy)"),
            ],
        },
        _VENDOR_REPORT: {},
        _PENDING_CRM: {
            file: [
                ('Record "EA Outbox Email"', 'Record "Synthetic Outbox Email"'),
                ("        HttpContent: HttpContent;\n", "        HttpContent: HttpContent;\n        ContentHeaders: HttpHeaders;\n"),
                ("HttpContent.GetHeaders().Clear();", "HttpContent.GetHeaders(ContentHeaders);\n" + indent + "ContentHeaders.Clear();"),
                ("HttpContent.GetHeaders().Add(", "ContentHeaders.Add("),
            ]
            for file, indent in (("src/ExternalCRMSync.Codeunit.al", "        "), ("src/OutboxEmailDispatcher.Codeunit.al", "                "))
        },
        _HTTP_LOCKS: {
            "src/AIContextBuilder.Codeunit.al": [("AgentTask.Description", "AgentTask.Title")],
            **{
                file: [
                    ('Record "EA Outbox Email"', 'Record "Synthetic Outbox Email"'),
                    ("Content.GetHeaders(ContentHeaders);", "Content.GetHeaders(ContentHeaders);\n" + indent + "ContentHeaders.Clear();"),
                ]
                for file, indent in (
                    ("src/CustomerDataExporter.Codeunit.al", "        "),
                    ("src/ExternalCRMSync.Codeunit.al", "        "),
                    ("src/OutboxEmailDispatcher.Codeunit.al", "                "),
                )
            },
        },
        _RESET: {
            "src/ServiceMgtSetup.Page.al": [
                ('page 50104 "Service Mgt. Setup"', 'page 50104 "Synthetic Service Mgt. Setup"'),
                ('Rec."Service Shipment Nos."', 'Rec."Posted Service Shipment Nos."'),
                ("Skip Manual Res. Alloc.", "Skip Manual Reservation"),
                ("skip manual resource allocation", "skip manual reservation"),
                ("Caption = 'Reset to Defaults';", "Caption = 'Reset to defaults';"),
            ]
        },
    }
    old_paths = set()
    for file in PatchSet(frozen_gold_entries[entry_id].patch):
        old_paths.add(file.path)
        source = "".join(line.value for hunk in file for line in hunk if not line.is_removed)
        for old, new in replacements[entry_id].get(file.path, []):
            source = source.replace(old, new)
        assert files[file.path] == source
    new_paths = {
        _COST_BASIS: {"src/SyntheticReceiptStatus.TableExt.al"},
        _VENDOR_REPORT: set(),
        _PENDING_CRM: {"src/SyntheticCRMCustomer.TableExt.al", "src/SyntheticOutboxEmail.Table.al"},
        _HTTP_LOCKS: {"src/SyntheticCRMCustomer.TableExt.al", "src/SyntheticOutboxEmail.Table.al"},
        _RESET: {"src/SyntheticServiceSetup.TableExt.al"},
    }
    assert set(files) - old_paths == new_paths[entry_id]


def test_cost_basis_gold_preserves_all_three_cost_branches_and_missing_item_trigger(materialized_entries):
    entry, files = materialized_entries[_COST_BASIS]
    source = files["src/BOMBufferMgt.Codeunit.al"]
    assert 'TotalCost += Item."Standard Cost" * BOMBuffer."Qty. per BOM Line"' in source
    assert 'TotalCost += Item."Unit Cost" * BOMBuffer."Qty. per BOM Line"' in source
    assert 'TotalCost += GetLastDirectCost(Item) * BOMBuffer."Qty. per BOM Line";' in source
    assert 'BOMBuffer."Unit Cost" := Item."Unit Cost";' in source
    assert 'BOMBuffer."Total Cost" := BOMBuffer."Unit Cost" * BOMBuffer."Qty. per BOM Line";' in source
    assert "                end;\n\n                // Update line with calculated cost\n                UpdateBOMLineWithCost(BOMBuffer, Item);" in source
    gold = entry.expected_comments[-1]
    assert gold.line_start == 59
    assert "do not prescribe a new costing policy" in gold.body
    assert 'PurchRcptLine.CalcFields("Currency Code");' in files["src/PurchRcptLineMgt.Codeunit.al"]
    assert 'field(50140; "Processed Date"; Date)' in files["src/SyntheticReceiptStatus.TableExt.al"]
    page = files["src/CustomReportLayoutsList.Page.al"]
    assert "trigger OnAfterGetRecord()" in page
    assert "User.Get(Rec.SystemModifiedBy)" in page
    assert "User.Get(Rec.SystemCreatedBy)" in page


def test_vendor_report_gold_has_a_literal_witness_distinct_from_csv_gold(materialized_entries):
    entry, files = materialized_entries[_VENDOR_REPORT]
    source = files["src/ReportBuilder.Codeunit.al"]
    header_match = re.search(r"VendorReportHeaderTok: Label '([^']*)'", source)
    separator_match = re.search(r"RowSeparatorTok: Label '([^']*)'", source)
    assert header_match is not None
    assert separator_match is not None
    header = header_match.group(1)
    separator = separator_match.group(1)
    assert "ReportBody := VendorReportHeaderTok;" in source
    assert "ReportBody += Format(VendorLedgerEntry.\"Entry No.\") + ' | ' +" in source
    assert 'Format(VendorLedgerEntry."Remaining Amount") + RowSeparatorTok;' in source
    # Literal concatenation witness, not AL runtime execution.
    assert header + "123 | 45" + separator == "Entry No. | Remaining Amount123 | 45; "
    assert entry.expected_comments[-1].line_start == 28
    assert entry.expected_comments[-1].severity == Severity.MEDIUM
    assert entry.expected_comments[3].line_start == 13
    assert "CSV" in entry.expected_comments[3].body


@pytest.mark.parametrize("entry_id", [_PENDING_CRM, _HTTP_LOCKS])
def test_privacy_dependencies_are_explicit_synthetic_persistent_records(materialized_entries, entry_id):
    _, files = materialized_entries[entry_id]
    customer = files["src/SyntheticCRMCustomer.TableExt.al"]
    outbox = files["src/SyntheticOutboxEmail.Table.al"]
    assert 'tableextension 57300 "Synthetic CRM Customer" extends Customer' in customer
    assert 'field(57300; "CRM Sync Required"; Boolean)' in customer
    assert 'table 57301 "Synthetic Outbox Email"' in outbox
    assert "Temporary" not in outbox
    assert "OptionMembers = Pending,Sent,Failed;" in outbox
    assert 'key(PK; "Entry No.")' in outbox
    assert "procedure GetBodyText(): Text\n    begin\n        exit(Body);" in outbox
    assert "field(5; Body; Text[2048])" in outbox
    for file, source in files.items():
        assert 'Record "EA Outbox Email"' not in source
        assert "GetHeaders()" not in source
        if "ContentHeaders.Add(" in source:
            assert source.index("ContentHeaders.Clear();") < source.index("ContentHeaders.Add(")
        if file.endswith(".Codeunit.al"):
            assert "PrivacyNotice" not in "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))


def test_blank_email_still_clears_pending_work_and_retains_unescaped_payload_gold(materialized_entries):
    entry, files = materialized_entries[_PENDING_CRM]
    source = files["src/ExternalCRMSync.Codeunit.al"]
    assert "if Customer.\"E-Mail\" = '' then\n            exit;" in source
    assert 'SyncCustomerToExternalCRM(Customer);\n                Customer."CRM Sync Required" := false;\n                Customer.Modify(false);' in source
    assert "JsonPayload := StrSubstNo(" in source
    assert "JsonPayload := StrSubstNo(" in files["src/OutboxEmailDispatcher.Codeunit.al"]
    assert entry.expected_comments[-1].line_start == 43
    assert entry.expected_comments[-1].severity == Severity.HIGH
    assert "Unsent work is marked complete" in entry.expected_comments[-1].body


def test_http_gold_keeps_lock_holding_paths_and_unauthenticated_graph_request(materialized_entries):
    entry, files = materialized_entries[_HTTP_LOCKS]
    crm = files["src/ExternalCRMSync.Codeunit.al"]
    outbox = files["src/OutboxEmailDispatcher.Codeunit.al"]
    assert "Customer.FindSet(true)" in crm
    assert 'SyncCustomerToExternalCRM(Customer);\n                Customer."CRM Sync Required" := false;\n                Customer.Modify(true);' in crm
    assert "HttpClient.Post(CrmSyncUrlTok, Content, Response);" in crm
    assert outbox.index("OutboxEmail.FindSet(true)") < outbox.index("HttpClient.Post(") < outbox.index("OutboxEmail.Modify(true)")
    assert "Commit(" not in crm + outbox
    assert "ReadIsolation" not in crm + outbox
    assert "https://graph.microsoft.com/v1.0/me/sendMail" in outbox
    assert "Authorization" not in outbox
    assert "DefaultRequestHeaders" not in outbox
    assert "HttpClient: HttpClient;" in outbox
    golds = entry.expected_comments[-3:]
    assert [(g.line_start, g.domain, g.severity) for g in golds] == [
        (33, "performance", Severity.MEDIUM),
        (15, "performance", Severity.MEDIUM),
        (22, "security", Severity.HIGH),
    ]
    assert "do not fix this with an unqualified per-row Commit" in golds[0].body
    assert "do not assume app-only tokens can call /me" in golds[2].body
    assert "AgentTask.Title" in files["src/AIContextBuilder.Codeunit.al"]
    assert 'User."Full Name"' in files["src/AIContextBuilder.Codeunit.al"]


def test_reset_gold_preserves_partial_reset_and_misleading_address_binding(materialized_entries):
    entry, files = materialized_entries[_RESET]
    source = files["src/ServiceMgtSetup.Page.al"]
    extension = files["src/SyntheticServiceSetup.TableExt.al"]
    assert 'field(50105; "Ship-to Address"; Text[100])' in extension
    assert 'field(50104; "Service Order Type"; Code[10])' in extension
    assert 'field("Enable Concurrent Posting"; Rec."Ship-to Address")' in source
    assert "ToolTip = 'Reset all settings to their default values.';" in source
    assert "Confirm('Are you sure you want to reset all settings to their default values?')" in source
    reset = source.split("    local procedure ResetToDefaults()", 1)[1]
    assert re.findall(r'Rec\."([^"]+)" :=', reset) == [
        "Default Response Time (Hours)",
        "One Service Item Line/Order",
        "Skip Manual Reservation",
        "Fault Reason Code Mandatory",
    ]
    assert "Rec.Init()" not in reset
    assert entry.expected_comments[-1].line_start == 168
    assert "do not blindly erase user configuration" in entry.expected_comments[-1].body


@pytest.mark.parametrize(("entry_id", "expected_count"), [(_SCAN, 2), (_API, 0), (_GROUPS, 1)])
def test_corrected_gold_classification_and_loader(materialized_entries, entry_id, expected_count):
    entry, _ = materialized_entries[entry_id]
    assert len(entry.expected_comments) == expected_count
    assert entry.ignored_comments == []
    assert all(comment.severity == Severity.MEDIUM for comment in entry.expected_comments)


def test_scan_gold_targets_a_real_linear_search_not_primary_key_get(materialized_entries):
    entry, files = materialized_entries[_SCAN]
    source = files["src/DataProcessor.Codeunit.al"]
    gold = entry.expected_comments[0]
    assert source.splitlines()[gold.line_start - 1 : gold.line_end] == [
        "        if TempItemCache.FindSet() then",
        "            repeat",
        '                if TempItemCache."No." = ItemNo then',
        "                    exit(true);",
        "            until TempItemCache.Next() = 0;",
    ]
    assert 'if not FindCachedItem(TempItemCache, SalesLine."No.") then begin' in source
    assert 'UnitCost := TempItemCache."Unit Cost";' in source
    assert "TempItemCache.Get(" not in source
    assert "TempItemCache.SetRange(" not in source
    assert "TempItemCache.SetFilter(" not in source
    assert source.count("SalesLine.SetRange(Type, SalesLine.Type::Item);") == 2
    assert 'UnitCostCache.Add(SalesLine."No.", Item."Unit Cost");' in source
    assert 'UnitCost := UnitCostCache.Get(SalesLine."No.");' in source
    assert "primary-key Get(ItemNo)" in gold.body
    assert "Dictionary" in gold.body
    assert gold.articles == ["performance/prefer-dictionary-over-temporary-table-for-lookups"]
    assert entry.metadata.articles == []


def test_api_boundary_has_persistent_reads_and_a_populated_temporary_control(materialized_entries):
    entry, files = materialized_entries[_API]
    outbox = files["src/OutboxEmailAPI.Page.al"]
    buffer = files["src/NameValueBufferAPI.Page.al"]
    for source in (outbox, buffer):
        assert "APIPublisher = 'bcbench';" in source
        assert all(f"{operation}Allowed = false;" in source for operation in ("Insert", "Modify", "Delete"))

    assert 'SourceTable = "Email Outbox";' in outbox
    assert "SourceTableTemporary" not in outbox
    assert "ODataKeyFields = SystemId;" in outbox
    assert "field(id; Rec.SystemId)" in outbox
    assert "field(entryNo; Rec.Id)" in outbox
    assert "Rec.Description" not in outbox
    assert "Rec.Status" not in outbox
    assert "SourceTableTemporary = true;" in buffer
    assert "ODataKeyFields = Name;" in buffer
    assert "trigger OnOpenPage()" in buffer
    assert "Rec.Name := 'companyName';" in buffer
    assert "Rec.Value := CompanyName();" in buffer
    assert "Rec.Insert();" in buffer
    aggregator = files["src/RecordSetAggregator.Codeunit.al"]
    assert "CalcFields(" not in aggregator
    assert 'Total += TempSalesLine."Outstanding Amount";' in aggregator
    assert 'MaxUnitPrice := TempItem."Unit Price";' in aggregator
    assert "exit(TempAnalysisReportChartSetup.Count());" in aggregator
    assert entry.metadata.articles == ["performance/do-not-remove-sourcetabletemporary-from-api-page"]
    assert entry.declared_articles() == set(entry.metadata.articles)


@pytest.mark.parametrize("group_codes", [("A", "B"), ("B", "A"), ("A", "B", "C")])
def test_regenerated_header_ids_lose_position_but_business_keys_restore_it(materialized_entries, group_codes):
    entry, files = materialized_entries[_GROUPS]
    table = files["src/Synthetic/TempGroupedLine.Table.al"]
    source = files["src/Synthetic/GroupedLinesRefresh.Codeunit.al"]
    assert 'field(3; "Group Code"; Code[20])' in table
    assert 'key(PK; "Entry No.") { Clustered = true; }' in table
    rebuild = source.split("    local procedure RebuildGroupHeaders", 1)[1]
    assert rebuild.split("    begin\n", 1)[1] == (
        "        TempGroupedLine.Reset();\n"
        "        if TempGroupedLine.FindFirst() then\n"
        '            NextEntryNo := TempGroupedLine."Entry No.";\n'
        "        TempGroupedLine.DeleteAll();\n"
        "        foreach GroupCode in GroupCodes do begin\n"
        "            NextEntryNo -= 1;\n"
        "            TempGroupedLine.Init();\n"
        '            TempGroupedLine."Entry No." := NextEntryNo;\n'
        '            TempGroupedLine."Group Code" := GroupCode;\n'
        "            TempGroupedLine.Insert();\n"
        "        end;\n"
        "    end;\n"
        "}\n"
    )
    gold = entry.expected_comments[0]
    assert source.splitlines()[gold.line_start - 1 : gold.line_end] == [
        "        if not TempGroupedLine.Get(CurrentEntryNo) then",
        "            if TempGroupedLine.FindFirst() then;",
        '        CurrentEntryNo := TempGroupedLine."Entry No.";',
    ]
    assert entry.declared_articles() == set()

    # Algorithm-level witness bound to the materialized AL above, not an AL runtime.
    rows: dict[int, str] = {}
    for _ in range(3):
        next_entry_no = min(rows, default=0)
        previous = rows
        rows = {next_entry_no - offset: code for offset, code in enumerate(group_codes, start=1)}
        assert set(rows.values()) == set(group_codes)
        if previous:
            selected_code = group_codes[0]
            old_id = next(key for key, code in previous.items() if code == selected_code)
            assert old_id not in rows
            fallback_id = min(rows)
            assert rows[fallback_id] != selected_code
            restored_id = next(key for key, code in rows.items() if code == selected_code)
            assert restored_id != old_id
            assert rows[restored_id] == selected_code


def test_validate_and_modify_triggers_are_not_required_bulk_replacement_gold(materialized_entries):
    entry, files = materialized_entries[_BULK]
    source = files["src/PaymentToleranceMgt.Codeunit.al"]
    assert 'SalesLine.Validate("Unit Price", NewPrice);' in source
    assert "SalesLine.Modify(true);" in source
    assert len(entry.expected_comments) == 1
    assert "Document Type" in entry.expected_comments[0].body
    assert "ModifyAll" not in entry.expected_comments[0].body
    assert entry.ignored_comments == []
    assert entry.metadata.articles == ["performance/prefer-modifyall-over-per-row-modify"]


def test_internal_recordref_helper_is_not_a_public_confused_deputy(materialized_entries):
    entry, files = materialized_entries[_INTERNAL]
    source = files["src/SecureOperationHelper.Codeunit.al"]
    assert "Access = Internal;" in source
    assert "internal procedure DeleteAllRecords(TableNo: Integer)" in source
    assert "RecRef.Open(TableNo);" in source
    assert "Permissions" not in source
    assert entry.expected_comments == []
    assert entry.ignored_comments == []
    assert entry.metadata.articles == ["security/recordref-open-with-caller-table-must-not-be-public"]


def test_setup_relation_gold_describes_rejection_not_invalid_persistence(materialized_entries):
    entry, files = materialized_entries[_RELATION]
    setup = files["src/SyntheticMfgSetupExt.TableExt.al"]
    seeder = files["src/SyntheticBOMSeeder.Codeunit.al"]
    gold = entry.expected_comments[0]
    assert setup.splitlines()[gold.line_start - 1].strip() == "TableRelation = Item;"
    assert "ProductionBOMLine.Validate(Type, ProductionBOMLine.Type::Item);" in seeder
    assert 'ProductionBOMLine.Validate("No.", ManufacturingSetup."Synth Default Comp. Item No.");' in seeder
    assert "Insert(" not in seeder
    assert "rejected when the default is applied" in gold.body
    assert "does not silently persist" in gold.body


def test_error_label_usage_is_not_rejected_for_including_remediation(materialized_entries):
    entry, files = materialized_entries[_STATEMENT]
    source = files["src/CloudMigReplicateDataMgt.Codeunit.al"]
    assert "TablesCannotBeEnabledForReplicationErr: Label" in source
    assert "Error(TablesCannotBeEnabledForReplicationErr, RestrictedTableNames);" in source
    assert not any("TablesCannotBeEnabledForReplicationErr" in gold.body for gold in entry.expected_comments)


def test_delivery_gold_consolidates_one_cause_and_fix_into_original_g05(materialized_entries):
    entry, files = materialized_entries[_NOTICE]
    source = files["src/CustomerNotification.Codeunit.al"]
    body = source.split("procedure SendOverdueNotice", 1)[1].split("    end;", 1)[0]
    assert "// SendEmail(Customer);" in body
    assert "Message('An overdue notice has been sent to the customer.');" in body
    assert "SendEmail(" not in "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
    findings = [gold for gold in entry.expected_comments if gold.file == "src/CustomerNotification.Codeunit.al" and gold.line_start == 7]
    assert len(findings) == 1
    assert findings[0] is entry.expected_comments[4]
    assert findings[0].domain == "error-handling"
    assert any("merely deleting the commented line does not fix" in gold.body for gold in findings)


def test_statement_semantic_finding_and_compiler_diagnostic_are_distinguished(materialized_entries):
    entry, files = materialized_entries[_STATEMENT]
    source = files["src/CustStPDFDocHandler.Codeunit.al"]
    processing = source.split("procedure ProcessCustomerStatement", 1)[1].split("    end;", 1)[0]
    assert "StatementGuid: Guid;" in processing
    assert "StatementGuid :=" not in processing
    assert processing.count("Error(") == 2
    assert "if IsNullGuid(StatementGuid) then" in processing
    assert "        try\n" in source
    assert "        except\n" in source
    assert "    end;\n\n        exit(GenerationSuccess);\n    end;" in source
    golds = [gold for gold in entry.expected_comments if gold.file == "src/CustStPDFDocHandler.Codeunit.al" and gold.domain == "error-handling"]
    assert [(gold.line_start, gold.line_end, gold.severity) for gold in golds] == [(14, 20, Severity.MEDIUM), (31, 39, Severity.HIGH)]
    assert [gold.kind for gold in golds] == [ReviewCommentKind.REVIEW_FINDING, ReviewCommentKind.COMPILER_DIAGNOSTIC]


def test_audit_dispositions_cover_every_original_miss_without_relabeling_uncertainty(before_first_gold_batch, frozen_gold_entries):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    audit = json.loads((dataset.parent / "audits" / "run-39616090167.json").read_text(encoding="utf-8"))
    entries = frozen_gold_entries
    rows = audit["rows"]
    assert len(rows) == len({row["row_id"] for row in rows}) == 97
    assert Counter(row["status"] for row in rows) == audit["disposition_counts"]
    assert audit["dataset_after_sha256"] == sha256(before_first_gold_batch).hexdigest()
    assert audit["historical_metrics"]["matched"] == 105
    assert audit["historical_metrics"]["expected"] == 202
    assert audit["historical_metrics"]["incorrect_by_gold_matching"] == 322
    assert audit["scope_only_sensitivity"]["matched"] == 95
    assert audit["scope_only_sensitivity"]["expected"] == 179
    assert audit["population"]["excluded_gold"] == 31
    assert audit["scoring_contract"]["official_assignment"] == "one-to-one"
    for row in rows:
        assert row["decision"]
        assert row["evidence"]
        assert row["row_id"] == f"{row['instance_id']}:G{row['original_gold_index']:02}"
        if row["status"] != "fixed":
            reassessment = row.get("integration_reassessment")
            if reassessment:
                assert ReviewComment.model_validate(reassessment["before"]).model_dump(exclude={"kind", "diagnostic_id"}) == ReviewComment.model_validate(row["original_gold"]).model_dump(
                    exclude={"kind", "diagnostic_id"}
                )
                assert reassessment["reason"]
            original = ReviewComment.model_validate(reassessment["after"] if reassessment else row["original_gold"])
            current = entries[row["instance_id"]].expected_comments
            assert any(gold.model_dump(exclude={"kind", "diagnostic_id"}) == original.model_dump(exclude={"kind", "diagnostic_id"}) for gold in current)
    for addition in audit["positive_gold_additions"]:
        assert any(gold.file == addition["file"] and gold.line_start == addition["line_start"] for gold in entries[addition["instance_id"]].expected_comments)


def test_mechanical_inventory_preserves_all_records_sources_and_symmetric_historical_scope(before_first_gold_batch, frozen_gold_entries):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    inventory = json.loads((dataset.parent / "audits" / "mechanical-gold-scope.json").read_text(encoding="utf-8"))
    entries = frozen_gold_entries
    assert inventory["status"] == "approved_classification_applied"
    assert inventory["classified_dataset_sha256"] == "1495700a9b4089851f6648754cc199cb1a410cb241e3f27ba51757d01204116f"
    assert inventory["current_dataset_sha256"] == sha256(before_first_gold_batch).hexdigest()
    assert len(entries) == len(inventory["entry_expected_counts"]) == 145
    assert sum(inventory["entry_expected_counts"].values()) == len(inventory["rows"]) == 233
    assert inventory["disposition_counts"] == {"retain": 188, "mechanical_neutral": 45}
    assert inventory["mechanical_kind_counts"] == {"analyzer_diagnostic": 40, "compiler_diagnostic": 5}
    assert inventory["mechanical_historical_counts"] == {"matched": 12, "missed": 22, "excluded_case": 10, "new_or_repaired_gold": 1}
    current_records = inventory["current_gold_records"]
    assert len(current_records) == 300
    assert inventory["current_kind_counts"] == {"review_finding": 235, "analyzer_diagnostic": 56, "compiler_diagnostic": 9}
    current_by_snapshot = {row["snapshot_row_id"]: row for row in current_records if row["snapshot_row_id"]}
    retired = {row["snapshot_row_id"] for row in inventory["integration_changes"] if row["status"] == "retired"}
    assert retired == {"synthetic__style-012:G14", "synthetic__upgrade-005:G01"}
    assert set(current_by_snapshot) | retired == {row["row_id"] for row in inventory["rows"]}
    for entry_id, entry in entries.items():
        assert sha256(entry.patch.encode()).hexdigest() == inventory["source_patch_sha256"][entry_id]
    for row in inventory["rows"]:
        original = ReviewComment.model_validate(row["gold"])
        assert row["reason"]
        assert row["source_excerpt"]
        if row["row_id"] in retired:
            continue
        current = current_by_snapshot[row["row_id"]]
        gold = entries[row["instance_id"]].expected_comments[current["gold_index"] - 1]
        changes = [change for change in inventory["integration_changes"] if change["snapshot_row_id"] == row["row_id"]]
        expected = ReviewComment.model_validate(changes[-1]["after"]) if changes else original
        assert gold.model_dump(exclude={"kind", "diagnostic_id"}) == expected.model_dump(exclude={"kind", "diagnostic_id"})
        assert gold.kind == (expected.kind if changes else row["classification"]["kind"])
        if gold.kind == ReviewCommentKind.ANALYZER_DIAGNOSTIC:
            assert gold.diagnostic_id == (expected.diagnostic_id if changes else row["rule"])
        elif gold.kind == ReviewCommentKind.COMPILER_DIAGNOSTIC:
            assert gold.diagnostic_id is None
    for record in current_records:
        gold = entries[record["instance_id"]].expected_comments[record["gold_index"] - 1]
        assert sha256(json.dumps(gold.model_dump(mode="json"), sort_keys=True).encode()).hexdigest() == record["gold_sha256"]
    for index in [1, 9, 10, 11, 12, 13]:
        assert entries[_NOTICE].expected_comments[index - 1].kind == ReviewCommentKind.REVIEW_FINDING


def test_false_delivery_addition_does_not_claim_recovery_of_an_original_false_positive():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    audit = json.loads((dataset.parent / "audits" / "run-39616090167.json").read_text(encoding="utf-8"))
    addition = next(row for row in audit["positive_gold_additions"] if row["instance_id"] == _NOTICE)
    assignment = addition["baseline_assignment"]
    assert addition["baseline_candidate"] == "F001"
    assert assignment["status"] == "matched"
    assert assignment["gold_row_id"] == f"{_NOTICE}:G05"
    assert assignment["in_original_322_unmatched_population"] is False
    assert assignment["assignment_ambiguous"] is False
    entry = next(entry for entry in CodeReviewEntry.load(dataset) if entry.instance_id == _NOTICE)
    assert assignment["gold_severity"] == assignment["generated_severity"] == entry.expected_comments[4].severity == Severity.MEDIUM
    assert audit["scope_union_sensitivity"]["incorrect_by_gold_matching"] == 322
    assert "Initial 45-neutral snapshot" in audit["scope_union_sensitivity"]["classification_stage"]
    assert "Resolved: one cause/fix" in addition["granularity_status"]


def test_unmatched_audit_covers_frozen_population_without_converting_adjudications_to_scores(before_first_gold_batch, frozen_gold_entries):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    ledger = json.loads((dataset.parent / "audits" / "run-39616090167-unmatched.json").read_text(encoding="utf-8"))
    entries = frozen_gold_entries
    rows = ledger["rows"]
    assert len(rows) == len({row["row_id"] for row in rows}) == 322
    assert len({row["instance_id"] for row in rows}) == 103
    assert ledger["effective_audit_version"] == "2.0"
    assert ledger["audit_input_sha256"]["comments.json"] == "a68ad1f4fea2b2a5a950a0fc4b15d23e589979e7867da2efb30ff9fef99e3eff"
    assert Counter(row["factual_correctness"] for row in rows) == {"supported": 148, "incorrect": 55, "mixed": 39, "unresolved": 80}
    assert Counter(row["primary_disposition"] for row in rows) == {
        "missing_gold": 80,
        "matching_or_granularity": 5,
        "duplicate": 7,
        "mechanical_neutral": 21,
        "severity_scope": 50,
        "genuine_false_positive": 78,
        "unresolved": 81,
    }
    assert ledger["dataset_after_sha256"] == sha256(before_first_gold_batch).hexdigest()
    assert len(ledger["source_packet_sha256"]) == 183
    assert len(ledger["entry_evidence"]) == 103
    assert f"{_NOTICE}:F001" not in {row["row_id"] for row in rows}
    for row in rows:
        assert len(row["original_comment_sha256"]) == 64
        evidence = ledger["entry_evidence"][row["instance_id"]]
        assert sha256(entries[row["instance_id"]].patch.encode()).hexdigest() == evidence["patch_sha256"]
        assert len(evidence["candidate_set_identity"]["candidate_sha256"]) == 64
        assert len(evidence["candidate_set_identity"]["frozen_json_sha256"]) == 64
        if row["primary_disposition"] == "unresolved":
            assert row["integration_decisions"] == []
    decisions = ledger["proposal_decisions"]
    addition_ids = [decision["row_id"] for decision in decisions if decision["group"] in {"concrete_additions", "other_missing_gold_candidates", "policy_additions"}]
    assert len(addition_ids) == len(set(addition_ids)) == 80
    assert set(addition_ids) == {row["row_id"] for row in rows if row["primary_disposition"] == "missing_gold"}
    assert Counter(decision["status"] for decision in decisions if decision["row_id"] in addition_ids) == {"accepted": 43, "already_covered": 1, "deferred": 36}
    assert ledger["decision_counts"] == {
        "concrete_additions": {"accepted": 37, "deferred": 3, "already_covered": 1},
        "gold_corrections_and_matching": {"accepted": 5, "deferred": 1},
        "mechanical_candidates": {"accepted_neutral": 19, "already_covered": 1, "reclassified_existing": 1},
        "other_missing_gold_candidates": {"accepted": 6, "deferred": 25},
        "policy_additions": {"deferred": 8},
        "whole_dataset_consistency": {"accepted": 7},
    }
    gold_hashes = {sha256(json.dumps(gold.model_dump(mode="json"), sort_keys=True).encode()).hexdigest() for entry in entries.values() for gold in entry.expected_comments}
    for decision in decisions:
        assert decision["reason"]
        if "gold_sha256" in decision:
            assert decision["gold_sha256"] in gold_hashes
    mixed_missing = [row for row in rows if row["primary_disposition"] == "missing_gold" and row["factual_correctness"] == "mixed"]
    assert len(mixed_missing) == 7
    assert all(row["integration_decisions"][0]["status"] == "accepted" for row in mixed_missing)


def test_integrated_neutral_diagnostics_keep_evidence_boundaries_and_correct_anchors(before_incidental_cleanup):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    entries = {entry.instance_id: entry for entry in (CodeReviewEntry.model_validate_json(line) for line in before_incidental_cleanup.splitlines())}
    ledger = json.loads((dataset.parent / "audits" / "run-39616090167-unmatched.json").read_text(encoding="utf-8"))
    inventory = json.loads((dataset.parent / "audits" / "mechanical-gold-scope.json").read_text(encoding="utf-8"))
    sources = {
        entry.instance_id: {file.path: {line.target_line_no: line.value.rstrip() for hunk in file for line in hunk if not line.is_removed} for file in PatchSet(entry.patch)}
        for entry in entries.values()
    }
    for record in inventory["current_gold_records"]:
        gold = entries[record["instance_id"]].expected_comments[record["gold_index"] - 1]
        if record["snapshot_row_id"] is None:
            lines = sources[record["instance_id"]][gold.file]
            assert lines[gold.line_start].strip()
            assert all(line in lines for line in range(gold.line_start, (gold.line_end or gold.line_start) + 1))
        if gold.diagnostic_id == "AA0218":
            assert "field(" in sources[record["instance_id"]][gold.file][gold.line_start]
        if gold.diagnostic_id == "AA0216":
            assert "AA0217" not in gold.body
    tooltip = ledger["aa0218_review"]
    assert len(tooltip["rows"]) == 11
    assert Counter(row["field_class"] for row in tooltip["rows"]) == {"Normal": 10, "FlowField": 1}
    assert tooltip["conclusion"]["effective_scope_unresolved_rows"] == 0
    assert entries["synthetic__style-018"].expected_comments[0].diagnostic_id == "AA0218"
    assert len(entries["synthetic__style-018"].expected_comments) == 1
    for gold in entries["synthetic__style-017"].expected_comments[3:6]:
        assert gold.kind == ReviewCommentKind.REVIEW_FINDING
        assert "AA0217" not in gold.body
    classified = entries["synthetic__style-field-repurpose-indent-01"].expected_comments[-1]
    assert classified.kind == ReviewCommentKind.ANALYZER_DIAGNOSTIC
    assert classified.diagnostic_id == "AS0016"
    assert classified.severity == Severity.HIGH
    api_gold = entries["synthetic__performance-clean-03"].expected_comments
    assert len(api_gold) == 2
    assert all(g.kind == ReviewCommentKind.COMPILER_DIAGNOSTIC and g.diagnostic_id == "AL0485" for g in api_gold)


def test_temporary_table_repair_uses_actual_base_and_does_not_invent_replacement_gold():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    entry = next(entry for entry in CodeReviewEntry.load(dataset) if entry.instance_id == "synthetic__upgrade-005")
    assert entry.base_commit == "a29ca6a99e6cd2bd46242f769b660ef1ec45b063"
    assert len(entry.expected_comments) == 2
    assert all("DataArchive.Table.al" in gold.file for gold in entry.expected_comments)
    inventory = json.loads((dataset.parent / "audits" / "mechanical-gold-scope.json").read_text(encoding="utf-8"))
    retired = next(row for row in inventory["integration_changes"] if row["snapshot_row_id"] == "synthetic__upgrade-005:G01")
    assert retired["status"] == "retired"
    assert retired["after"] is None
    assert "physical table" in retired["before"]["body"]
    assert "a29ca6a" in retired["reason"]


def test_dataset_alignment_keeps_mechanical_misses_and_changes_only_three_gold_bodies(before_first_gold_batch):
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    inventory = json.loads((dataset.parent / "audits" / "mechanical-gold-scope.json").read_text(encoding="utf-8"))
    misses = json.loads((dataset.parent / "audits" / "run-39616090167.json").read_text(encoding="utf-8"))
    alignment = inventory["alignment_review"]
    assert alignment["after_dataset_sha256"] == sha256(before_first_gold_batch).hexdigest()
    assert alignment["before_dataset_sha256"] == "f30803905a7a1235688d151384490ce1f998214d614dea8ad117ed49bbcb39a4"
    assert alignment["knowledge_commit"] == "45cbe369527bbe6d4cad0b2a877bd1d61a617cdb"
    assert len(alignment["reviewed_articles"]) == 9
    assert alignment["missing_gold_dispositions"] == {"accepted": 43, "already_covered": 1, "deferred": 36}
    changes = [change for change in inventory["integration_changes"] if change.get("alignment_review") == alignment["id"]]
    assert {change["snapshot_row_id"] for change in changes} == {"synthetic__performance-007:G01", "synthetic__performance-015:G02", "synthetic__style-016:G03"}
    for change in changes:
        before = ReviewComment.model_validate(change["before"])
        after = ReviewComment.model_validate(change["after"])
        assert before.model_dump(exclude={"body"}) == after.model_dump(exclude={"body"})
        assert before.body != after.body
        assert change["sources"]
    neutral_misses = [row for row in misses["rows"] if row["status"] == "mechanical_neutral"]
    assert len(neutral_misses) == 22
    records = {row["snapshot_row_id"]: row for row in inventory["current_gold_records"] if row["snapshot_row_id"]}
    assert all(records[row["mechanical_inventory_row"]]["kind"] == "analyzer_diagnostic" for row in neutral_misses)
    assert Counter(records[row["mechanical_inventory_row"]]["diagnostic_id"] for row in neutral_misses) == {
        "AA0216": 17,
        "AA0248": 1,
        "AA0018": 1,
        "AA0013": 1,
        "AA0001": 1,
        "AA0137": 1,
    }
    arms = misses["comparison_arms"]
    assert arms["status"] == "paused_dataset_revised_no_new_pair"
    assert arms["superseded_bench_pair"]["dataset_sha256"] == alignment["before_dataset_sha256"]
    assert arms["superseded_bench_pair"]["baseline_results_rewritten"] is False
    assert arms["superseded_bench_pair"]["candidate_dispatched"] is False


def test_findset_gold_describes_update_intent_without_inventing_blocking_or_round_trips():
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(EvaluationCategory.CODE_REVIEW.dataset_path)}
    reader = entries["synthetic__performance-007"]
    writer = entries["synthetic__performance-015"]
    assert "Customer.FindSet(true)" in reader.patch
    assert 'Result.Append(Customer."No.")' in reader.patch
    assert "Customer.Modify" not in reader.patch
    assert "VATEntry.FindSet()" in writer.patch
    assert "VATEntry.Modify(false)" in writer.patch
    assert "VATEntry.LockTable" not in writer.patch
    assert "VATEntry.ReadIsolation" not in writer.patch
    assert "they do not block every reader" in reader.expected_comments[0].body
    assert "unless a separate consistency requirement" in reader.expected_comments[0].body
    assert "FindSet(false) still permits Modify" in writer.expected_comments[1].body
    assert "Consider FindSet(true)" in writer.expected_comments[1].body
    assert "does not establish a separate network round-trip per row" in writer.expected_comments[1].body
    assert "AA0216, AA0216" not in entries["synthetic__style-016"].expected_comments[2].body
