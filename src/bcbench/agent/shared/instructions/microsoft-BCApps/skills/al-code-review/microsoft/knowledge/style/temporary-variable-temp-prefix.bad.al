codeunit 50217 "Sample Temp Prefix Bad"
{
    procedure BuildBuffer(var SalesLine: Record "Sales Line" temporary)
    var
        WIPBuffer: Record "Job WIP Buffer" temporary;
    begin
        WIPBuffer.Init();
        WIPBuffer.Insert();
        SalesLine.Init();
        SalesLine.Insert();
    end;
}
