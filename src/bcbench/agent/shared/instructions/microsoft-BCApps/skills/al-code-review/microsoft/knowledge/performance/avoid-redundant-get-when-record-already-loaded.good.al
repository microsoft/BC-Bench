page 50216 "Perf Sample Redundant Good"
{
    PageType = ListPart;
    SourceTable = "Assembly Line";

    var
        ShowWarning: Boolean;

    trigger OnAfterGetRecord()
    begin
        ShowWarning := CheckAvailability(Rec);
    end;

    local procedure CheckAvailability(var AssemblyLine: Record "Assembly Line"): Boolean
    begin
        exit(AssemblyLine.Quantity > 0);
    end;
}
