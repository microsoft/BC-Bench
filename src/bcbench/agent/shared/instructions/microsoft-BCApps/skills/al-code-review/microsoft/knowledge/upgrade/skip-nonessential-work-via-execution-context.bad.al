codeunit 50217 "Report Selection Seeder"
{
    procedure AddReportSelectionEntries()
    var
        ReportSelections: Record "Report Selections";
    begin
        // No context check — fires during upgrade and silently inserts rows
        // the upgrade pipeline never asked for.
        ReportSelections.Init();
        ReportSelections.Insert();
    end;
}
