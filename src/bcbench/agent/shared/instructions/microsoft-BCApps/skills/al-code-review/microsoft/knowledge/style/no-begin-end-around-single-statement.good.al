codeunit 50236 "Sample Single Stmt Good"
{
    procedure Validate(IsAssemblyOutputLine: Boolean)
    var
        SalesLine: Record "Sales Line";
    begin
        if IsAssemblyOutputLine then
            SalesLine.TestField("Order Line No.", 0);
    end;
}
