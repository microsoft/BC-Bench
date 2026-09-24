import json
import subprocess

import pytest
from unidiff import PatchSet

from bcbench.dataset.codereview import CodeReviewEntry, Severity
from bcbench.operations.git_operations import apply_patch, init_repo
from bcbench.types import EvaluationCategory

_SCAN = "synthetic__performance-014"
_API = "synthetic__performance-009"
_GROUPS = "synthetic__error-handling-drilldown-position-01"
_ENTRY_IDS = (_SCAN, _API, _GROUPS)


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
        assert raw["expect_findings"] is bool(entry.expected_comments)
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


@pytest.mark.parametrize(("entry_id", "expected_count"), [(_SCAN, 1), (_API, 0), (_GROUPS, 1)])
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
