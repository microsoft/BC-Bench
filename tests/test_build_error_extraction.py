from bcbench.exceptions import _extract_compiler_errors

SAMPLE_BUILD_OUTPUT = """\
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Manufacturing\\Routing\\RoutingVersion.Table.al(111,31): warning AL0432: Codeunit 'NoSeriesManagement' is marked for removal. Reason: Please use the "No. Series" and "No. Series - Batch" codeunits instead. Tag: 24.0.
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Manufacturing\\Reports\\CostSharesBreakdown.Report.al(66,37): warning AL0254: Sorting field 'Order Line No.' should be part of the keys for table 'Capacity Ledger Entry'
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Manufacturing\\Document\\ProductionOrder.Table.al(701,38): warning AL0432: Codeunit 'NoSeriesManagement' is marked for removal. Reason: Please use the "No. Series" and "No. Series - Batch" codeunits instead. Tag: 24.0.
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Utilities\\DataClassificationEvalData.Codeunit.al(3776,29): error AL0185: Table 'Agent Task Step' is missing
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Utilities\\DataClassificationEvalData.Codeunit.al(3778,38): error AL0185: Table 'Agent Task Timeline Entry' is missing
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Utilities\\DataClassificationEvalData.Codeunit.al(3779,42): error AL0185: Table 'Agent Task Timeline Entry Step' is missing
  C:\\Source\\App\\Layers\\W1\\BaseApp\\Utilities\\DataClassificationEvalData.Codeunit.al(3780,34): error AL0185: Table 'Agent Task Pane Entry' is missing
  C:\\Source\\App\\Layers\\W1\\BaseApp\\System\\Utilities\\TypeHelper.Codeunit.al(670,22): error AL0185: DotNet 'Environment' is missing
  C:\\Source\\App\\Layers\\W1\\BaseApp\\System\\XML\\XMLDOMManagement.Codeunit.al(763,28): error AL0185: DotNet 'Environment' is missing

  Compilation ended at '15:58:37.771'.

  App generation failed with exit code 1
  Compile-AppInBcContainer Telemetry Correlation Id: d8ab0073-0738-46bd-8b87-a92ad5770a5c
"""


class TestExtractCompilerErrors:
    def test_extracts_error_and_warning_lines(self):
        result = _extract_compiler_errors(SAMPLE_BUILD_OUTPUT)

        assert ": error AL0185:" in result
        assert ": warning AL0432:" in result
        assert ": warning AL0254:" in result

    def test_excludes_non_error_lines(self):
        result = _extract_compiler_errors(SAMPLE_BUILD_OUTPUT)

        assert "Compilation ended" not in result
        assert "App generation failed" not in result
        assert "Telemetry Correlation Id" not in result

    def test_returns_all_error_lines(self):
        result = _extract_compiler_errors(SAMPLE_BUILD_OUTPUT)
        lines = result.splitlines()

        # 3 warnings + 6 errors = 9 total
        assert len(lines) == 9

    def test_respects_max_lines(self):
        result = _extract_compiler_errors(SAMPLE_BUILD_OUTPUT, max_lines=3)
        lines = result.splitlines()

        assert len(lines) == 3

    def test_returns_empty_string_for_empty_input(self):
        assert _extract_compiler_errors("") == ""

    def test_fallback_to_last_lines_when_no_errors(self):
        output = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        result = _extract_compiler_errors(output, max_lines=2)

        assert result == "Line 4\nLine 5"

    def test_fallback_respects_max_lines(self):
        output = "\n".join(f"Line {i}" for i in range(100))
        result = _extract_compiler_errors(output, max_lines=10)
        lines = result.splitlines()

        assert len(lines) == 10
        assert lines[-1] == "Line 99"
