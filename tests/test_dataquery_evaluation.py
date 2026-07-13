from bcbench.evaluate.dataquery import result_sets_match
from bcbench.operations import wrap_query_as_api


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


class TestWrapQueryAsApi:
    PLAIN_QUERY = 'query 50100 MyQuery\n{\n    QueryType = Normal;\n\n    elements\n    {\n        dataitem(Customer; Customer)\n        {\n            column(No; "No.") { }\n        }\n    }\n}'

    def test_reassigns_object_id(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50101)
        assert "query 50101 MyQuery" in wrapped
        assert "query 50100" not in wrapped

    def test_injects_api_properties(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "QueryType = API;" in wrapped
        assert "APIPublisher = 'bcbench';" in wrapped
        assert "EntitySetName = 'bcbenchResults';" in wrapped

    def test_drops_existing_querytype(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "QueryType = Normal;" not in wrapped

    def test_preserves_query_body(self):
        wrapped = wrap_query_as_api(self.PLAIN_QUERY, 50100)
        assert "dataitem(Customer; Customer)" in wrapped
        assert 'column(No; "No.")' in wrapped
