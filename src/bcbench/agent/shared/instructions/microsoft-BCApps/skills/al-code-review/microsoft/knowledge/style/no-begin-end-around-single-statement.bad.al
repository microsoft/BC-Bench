codeunit 50237 "Sample Single Stmt Bad"
{
    procedure Validate(IsAssemblyOutputLine: Boolean)
    var
        SalesLine: Record "Sales Line";
    begin
        if IsAssemblyOutputLine then begin
            SalesLine.TestField("Order Line No.", 0);
        end;
    end;
}
