codeunit 50230 "Perf Sample SetCurrentKey Good"
{
    procedure ProcessLines(var SalesHeader: Record "Sales Header")
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetCurrentKey("Document Type", "Document No.", "Line No.");
        SalesLine.SetRange("Document Type", SalesHeader."Document Type");
        SalesLine.SetRange("Document No.", SalesHeader."No.");
        if SalesLine.FindSet() then
            repeat
                // ...
            until SalesLine.Next() = 0;
    end;
}
