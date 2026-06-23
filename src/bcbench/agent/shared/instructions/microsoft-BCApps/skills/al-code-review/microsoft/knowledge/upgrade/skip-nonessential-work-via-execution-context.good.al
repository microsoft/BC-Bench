codeunit 50216 "Report Selection Seeder"
{
    procedure AddReportSelectionEntries()
    var
        ReportSelections: Record "Report Selections";
    begin
        // Do not add report-selection entries during upgrade; the upgrade pipeline
        // does not need them and re-running this on every upgrade is wasteful.
        if GetExecutionContext() = ExecutionContext::Upgrade then
            exit;

        ReportSelections.Init();
        ReportSelections.Insert();
    end;
}
