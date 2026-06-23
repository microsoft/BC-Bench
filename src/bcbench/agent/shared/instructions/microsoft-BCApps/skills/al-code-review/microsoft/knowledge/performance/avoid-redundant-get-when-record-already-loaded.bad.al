page 50217 "Perf Sample Redundant Bad"
{
    PageType = ListPart;
    SourceTable = "Assembly Line";

    var
        AssemblyLineRec: Record "Assembly Line";
        ShowWarning: Boolean;

    trigger OnAfterGetRecord()
    begin
        // Redundant: the platform already fetched the row into Rec.
        AssemblyLineRec.Get("Document Type", "Document No.", "Line No.");
        ShowWarning := CheckAvailability(AssemblyLineRec);
    end;

    local procedure CheckAvailability(var AssemblyLine: Record "Assembly Line"): Boolean
    begin
        exit(AssemblyLine.Quantity > 0);
    end;
}
