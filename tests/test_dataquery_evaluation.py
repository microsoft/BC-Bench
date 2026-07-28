import pytest

from bcbench.evaluate.dataquery import result_sets_match
from bcbench.exceptions import BuildError
from bcbench.operations import bc_operations, wrap_query_as_api


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
        assert result_sets_match([{"Total": 500}], [{"Total": "500.0"}])

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
        assert not result_sets_match([{"Total": "1.00001"}], [{"Total": "1.00002"}])

    def test_high_precision_preserved(self):
        assert result_sets_match([{"Total": "1.000000001"}], [{"Total": "1.000000001"}])
        assert not result_sets_match([{"Total": "1.000000001"}], [{"Total": "1.000000002"}])

    def test_scale_insensitive(self):
        assert result_sets_match([{"Total": "500"}], [{"Total": "500.00"}])


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


class TestQueryRunTemplate:
    def _render(self):
        return bc_operations._QUERY_RUN_TEMPLATE.substitute(
            app_utils_path="AppUtils.psm1",
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


class TestWithholdGoldFromAgent:
    def _write_dataset(self, tmp_path):
        import json

        path = tmp_path / "dataquery.jsonl"
        entries = [
            {"instance_id": "q1", "nl_prompt": "count customers", "gold_query": "query 50100 A { }"},
            {"instance_id": "q2", "nl_prompt": "sum sales", "gold_query": "query 50101 B { }"},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return path

    def test_gold_hidden_during_and_restored_after(self, tmp_path):
        import json

        from bcbench.evaluate.dataquery import _withhold_gold_from_agent

        path = self._write_dataset(tmp_path)
        original = path.read_text(encoding="utf-8")

        with _withhold_gold_from_agent(path):
            during = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            # Gold is gone from disk while the agent runs, but the prompt/id the agent needs remain.
            assert all("gold_query" not in e for e in during)
            assert [e["instance_id"] for e in during] == ["q1", "q2"]
            assert [e["nl_prompt"] for e in during] == ["count customers", "sum sales"]

        # Restored verbatim once the agent phase completes.
        assert path.read_text(encoding="utf-8") == original

    def test_gold_restored_on_exception(self, tmp_path):
        from bcbench.evaluate.dataquery import _withhold_gold_from_agent

        path = self._write_dataset(tmp_path)
        original = path.read_text(encoding="utf-8")

        with pytest.raises(RuntimeError), _withhold_gold_from_agent(path):
            raise RuntimeError("agent crashed")

        assert path.read_text(encoding="utf-8") == original

    def test_missing_dataset_is_noop(self, tmp_path):
        from bcbench.evaluate.dataquery import _withhold_gold_from_agent

        missing = tmp_path / "does-not-exist.jsonl"
        with _withhold_gold_from_agent(missing):
            pass
        assert not missing.exists()
