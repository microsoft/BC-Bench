import json
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
_ENTRY_IDS = (_SCAN, _API, _GROUPS, _BULK, _INTERNAL, _RELATION, _NOTICE, _STATEMENT)


def _unique_object(pairs):
    assert len(dict(pairs)) == len(pairs), "Duplicate JSON object keys"
    return dict(pairs)


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
    assert [(gold.line_start, gold.line_end, gold.severity) for gold in golds] == [(14, 21, Severity.MEDIUM), (32, 40, Severity.HIGH)]
    assert [gold.kind for gold in golds] == [ReviewCommentKind.REVIEW_FINDING, ReviewCommentKind.COMPILER_DIAGNOSTIC]


def test_audit_dispositions_cover_every_original_miss_without_relabeling_uncertainty():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    audit = json.loads((dataset.parent / "audits" / "run-39616090167.json").read_text(encoding="utf-8"))
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(dataset)}
    rows = audit["rows"]
    assert len(rows) == len({row["row_id"] for row in rows}) == 97
    assert Counter(row["status"] for row in rows) == audit["disposition_counts"]
    assert audit["dataset_after_sha256"] == sha256(dataset.read_bytes()).hexdigest()
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


def test_mechanical_inventory_preserves_all_records_sources_and_symmetric_historical_scope():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    inventory = json.loads((dataset.parent / "audits" / "mechanical-gold-scope.json").read_text(encoding="utf-8"))
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(dataset)}
    assert inventory["status"] == "approved_classification_applied"
    assert inventory["classified_dataset_sha256"] == "1495700a9b4089851f6648754cc199cb1a410cb241e3f27ba51757d01204116f"
    assert inventory["current_dataset_sha256"] == sha256(dataset.read_bytes()).hexdigest()
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


def test_unmatched_audit_covers_frozen_population_without_converting_adjudications_to_scores():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    ledger = json.loads((dataset.parent / "audits" / "run-39616090167-unmatched.json").read_text(encoding="utf-8"))
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(dataset)}
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
    assert ledger["dataset_after_sha256"] == sha256(dataset.read_bytes()).hexdigest()
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


def test_integrated_neutral_diagnostics_keep_evidence_boundaries_and_correct_anchors():
    dataset = EvaluationCategory.CODE_REVIEW.dataset_path
    entries = {entry.instance_id: entry for entry in CodeReviewEntry.load(dataset)}
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
