import json
from pathlib import Path

import pytest

from bcbench.evaluate.dataquery import DataQueryPipeline, _load_answer_rows, result_sets_match
from bcbench.exceptions import BuildError, EmptyGoldResultError
from bcbench.operations import bc_operations, wrap_query_as_api
from bcbench.types import AgentHarness, ContainerConfig, EvaluationCategory, EvaluationContext
from tests.conftest import create_data_query_entry


class TestResultSetsMatch:
    def test_identical_rows_match(self):
        rows = [{"No": "C1", "Total": 100}, {"No": "C2", "Total": 200}]
        assert result_sets_match(rows, rows)

    def test_row_order_ignored_when_unordered(self):
        generated = [{"No": "C2", "Total": 200}, {"No": "C1", "Total": 100}]
        gold = [{"No": "C1", "Total": 100}, {"No": "C2", "Total": 200}]
        assert result_sets_match(generated, gold, ordered=False)

    def test_row_order_enforced_when_ordered(self):
        generated = [{"No": "C2", "Total": 200}, {"No": "C1", "Total": 100}]
        gold = [{"No": "C1", "Total": 100}, {"No": "C2", "Total": 200}]
        assert not result_sets_match(generated, gold, ordered=True)

    def test_numeric_normalization(self):
        # Amounts arrive as numeric JSON types on both sides; scale differences must not matter.
        assert result_sets_match([{"Total": 500}], [{"Total": 500.0}])

    def test_column_names_ignored(self):
        assert result_sets_match([{"ItemNo": "I1", "Qty": 5}], [{"No": "I1", "Total": 5}])

    def test_odata_metadata_keys_ignored(self):
        generated = [{"@odata.etag": "W/abc", "No": "C1", "Total": 100}]
        gold = [{"No": "C1", "Total": 100}]
        assert result_sets_match(generated, gold)

    def test_mismatch_detected(self):
        assert not result_sets_match([{"No": "C1", "Total": 100}], [{"No": "C1", "Total": 999}])

    def test_different_row_count_mismatch(self):
        assert not result_sets_match([{"No": "C1"}], [{"No": "C1"}, {"No": "C2"}])

    def test_close_but_distinct_values_do_not_match(self):
        # Guards against numeric rounding collapsing distinct values into a false positive.
        assert not result_sets_match([{"Total": 1.00001}], [{"Total": 1.00002}])

    def test_high_precision_preserved(self):
        assert result_sets_match([{"Total": 1.000000001}], [{"Total": 1.000000001}])
        assert not result_sets_match([{"Total": 1.000000001}], [{"Total": 1.000000002}])

    def test_scale_insensitive(self):
        assert result_sets_match([{"Total": 500}], [{"Total": 500.00}])

    def test_digit_only_code_strings_not_collapsed(self):
        # BC Code/No. fields are JSON strings even when digit-only: "001" and "1" are DISTINCT records
        # and must never be scored as matching just because they are numerically equal.
        assert not result_sets_match([{"No": "001"}], [{"No": "1"}])
        assert not result_sets_match([{"No": "0010"}], [{"No": "10"}])

    def test_identical_code_strings_match(self):
        assert result_sets_match([{"No": "001", "Name": "Acme"}], [{"No": "001", "Name": "Acme"}])

    def test_numeric_string_not_coerced_to_number(self):
        # A code that happens to look like a scaled number must not match the numeric value 1.
        assert not result_sets_match([{"Key": "1.0"}], [{"Key": 1}])

    def test_two_empty_sets_match(self):
        # Documents the pitfall the empty-gold guard defends against: empty-vs-empty compares equal,
        # so an agent that retrieved nothing would spuriously "resolve" against an empty gold.
        assert result_sets_match([], [])


class TestGoldRowsEmptyGuard:
    def _context(self, tmp_path: Path) -> EvaluationContext:
        return EvaluationContext(
            entry=create_data_query_entry(
                instance_id="dataquery__customer-count-by-country-1",
                gold_query="query 50101 Q { elements { } }",
                environment_setup_version="29.0",
            ),
            repo_path=tmp_path / "repo",
            result_dir=tmp_path / "results",
            container=ContainerConfig("bcbench", "admin", "secret", company="CRONUS"),
            model="test-model",
            agent_name=AgentHarness.COPILOT,
            category=EvaluationCategory.DATA_QUERY,
        )

    def test_empty_gold_raises(self, tmp_path, monkeypatch):
        # An empty gold means the environment/harness is broken, not a valid expected answer. It must
        # fail loudly so a run that retrieved nothing can't score as resolved via empty-vs-empty.
        monkeypatch.setattr("bcbench.operations.execute_al_query", lambda *args, **kwargs: [])

        with pytest.raises(EmptyGoldResultError):
            DataQueryPipeline()._gold_rows(self._context(tmp_path))

    def test_non_empty_gold_returned(self, tmp_path, monkeypatch):
        rows = [{"CountryRegionCode": "US", "CustomerCount": 3}]
        monkeypatch.setattr("bcbench.operations.execute_al_query", lambda *args, **kwargs: rows)

        assert DataQueryPipeline()._gold_rows(self._context(tmp_path)) == rows


class TestLoadAnswerRows:
    def _write(self, tmp_path, content: str):
        p = tmp_path / "answer.json"
        p.write_text(content, encoding="utf-8")
        return p

    def test_bare_array(self, tmp_path):
        rows = _load_answer_rows(self._write(tmp_path, '[{"No": "C1", "Total": 100}]'))
        assert rows == [{"No": "C1", "Total": 100}]

    def test_single_object_becomes_one_row(self, tmp_path):
        assert _load_answer_rows(self._write(tmp_path, '{"Total": 42}')) == [{"Total": 42}]

    def test_odata_value_wrapper_unwrapped(self, tmp_path):
        rows = _load_answer_rows(self._write(tmp_path, '{"@odata.context": "x", "value": [{"No": "C1"}]}'))
        assert rows == [{"No": "C1"}]

    def test_empty_file_is_empty_list(self, tmp_path):
        assert _load_answer_rows(self._write(tmp_path, "")) == []

    def test_invalid_json_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not valid JSON"):
            _load_answer_rows(self._write(tmp_path, "{not json"))

    def test_non_object_rows_raise(self, tmp_path):
        with pytest.raises(TypeError, match="must be JSON objects"):
            _load_answer_rows(self._write(tmp_path, "[1, 2, 3]"))


class TestWrapQueryAsApi:
    PLAIN_QUERY = 'query 50100 MyQuery\n{\n    QueryType = Normal;\n\n    elements\n    {\n        dataitem(Customer; Customer)\n        {\n            column(No; "No.") { }\n        }\n    }\n}'
    LONG_NAME_QUERY = 'query 50100 "Items on Open Sales and Purchase Orders"\n{\n    elements\n    {\n        dataitem(Item; Item)\n        {\n            column(No; "No.") { }\n        }\n    }\n}'

    def test_reassigns_object_id_and_name(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50101)
        assert "query 50101 BCBenchQuery50101" in wrapped
        assert "query 50100" not in wrapped
        assert "MyQuery" not in wrapped

    def test_normalizes_overlong_quoted_name(self):
        # A descriptive >30-char name would trip AL0305; the harness normalizes it away.
        wrapped = wrap_query_as_api(self.LONG_NAME_QUERY, 50100)
        assert "query 50100 BCBenchQuery50100" in wrapped
        assert "Items on Open Sales and Purchase Orders" not in wrapped

    def test_injects_api_properties(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "QueryType = API;" in wrapped
        assert "APIPublisher = 'bcbench';" in wrapped
        assert "EntitySetName = 'bcbenchResults50100';" in wrapped

    def test_generated_and_gold_use_distinct_entity_sets(self):
        # Both apps can be published to the same tenant; distinct entity sets avoid an OData route collision.
        generated = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        gold = wrap_query_as_api(self.PLAIN_QUERY, 50101)
        assert "EntitySetName = 'bcbenchResults50100';" in generated
        assert "EntitySetName = 'bcbenchResults50101';" in gold

    def test_drops_existing_querytype(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "QueryType = Normal;" not in wrapped

    def test_preserves_query_body(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "dataitem(Customer; Customer)" in wrapped
        assert 'column(No; "No.")' in wrapped

    def test_uppercase_query_keyword_reassigned(self):
        wrapped = wrap_query_as_api('Query 50123 "My Q"\n{\n    elements { }\n}', 50100)
        assert "50100 BCBenchQuery50100" in wrapped
        assert "50123" not in wrapped

    def test_compact_and_cased_querytype_removed(self):
        # QueryType on the same line as the brace (no leading newline) and in any casing must still
        # be stripped, else the injected QueryType = API duplicates the property.
        wrapped = wrap_query_as_api("query 50100 Q\n{ querytype = Normal; elements { } }", 50100)
        assert wrapped.count("QueryType") == 1
        assert "QueryType = API;" in wrapped

    def test_missing_brace_raises_builderror(self):
        with pytest.raises(BuildError):
            wrap_query_as_api("query 50100 MyQuery no body here", 50100)

    def test_no_query_declaration_raises_builderror(self):
        with pytest.raises(BuildError):
            wrap_query_as_api("codeunit 50100 NotAQuery { }", 50100)


def test_execute_al_query_bootstraps_app_manifest(tmp_path, monkeypatch):
    app_dir = tmp_path / ".bcbench-query-generated"

    def write_empty_result(*args, **kwargs):
        (app_dir / "result.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(bc_operations.subprocess, "run", write_empty_result)

    rows = bc_operations.execute_al_query(
        'query 50100 MyQuery { elements { dataitem(Customer; Customer) { column(No; "No.") { } } } }',
        ContainerConfig(name="bcserver", username="admin", password="password"),
        "26.0.12345.0",
        tmp_path,
        "generated",
        company="CRONUS",
    )

    manifest = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
    assert rows == []
    assert manifest["name"] == "BC-Bench Query generated"
    assert manifest["idRanges"] == [{"from": 50100, "to": 50100}]
    assert manifest["runtime"] == "15.0"


class TestQueryRunTemplate:
    def _render(self):
        return bc_operations._QUERY_RUN_TEMPLATE.substitute(
            app_utils_path="AppUtils.psm1",
            suffix="generated",
            container_name="c",
            username="u",
            password="p",
            app_dir="d",
            app_name="BC-Bench Query generated",
            app_publisher="BC-Bench",
            publisher=bc_operations._QUERY_API_PUBLISHER,
            group=bc_operations._QUERY_API_GROUP,
            version=bc_operations._QUERY_API_VERSION,
            entity_set=bc_operations._entity_set_name(50100),
            result_file="r",
            company="CRONUS",
        )

    def test_uses_proven_build_helper(self):
        assert "Invoke-AppBuildAndPublish" in self._render()

    def test_fetches_from_inside_container(self):
        script = self._render()
        assert "Invoke-ScriptInBcContainer" in script
        assert "http://localhost:7048/BC/api" in script

    def test_does_not_use_credential_over_http(self):
        # PowerShell 7 (inside the container) refuses -Credential over plain HTTP; we must build a
        # Basic auth header by hand instead.
        script = self._render()
        assert "-Credential" not in script.split("Invoke-ScriptInBcContainer", 1)[1]
        assert "Authorization" in script
        assert "Basic " in script

    def test_follows_odata_nextlink(self):
        # Result sets larger than one OData page must not be silently truncated.
        assert "@odata.nextLink" in self._render()

    def test_uninstalls_throwaway_app(self):
        # Re-running against the same container must not fail with an object-ID conflict.
        script = self._render()
        assert "UnPublish-BcContainerApp" in script
        assert "UnInstall-BcContainerApp" in script

    def test_pins_company_by_name(self):
        # The gold query runs against the pinned company (passed to the scriptblock), not whatever
        # company happens to be first in the collection.
        script = self._render()
        assert "$_.name -eq $company" in script
        assert "'CRONUS'" in script

    def test_logs_each_phase(self):
        # Each of the four phases prints a tagged marker so a CI run shows which phase it reached
        # (and where it failed/timed out) inside the otherwise-opaque single pwsh -Command blob.
        script = self._render()
        for phase in ("Phase 1/4", "Phase 2/4", "Phase 3/4", "Phase 4/4"):
            assert phase in script
        assert "[query-generated]" in script
