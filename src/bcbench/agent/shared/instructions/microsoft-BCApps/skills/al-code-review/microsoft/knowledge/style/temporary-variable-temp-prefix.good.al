codeunit 50216 "Sample Temp Prefix Good"
{
    procedure BuildBuffer(var TempSalesLine: Record "Sales Line" temporary)
    var
        TempJobWIPBuffer: Record "Job WIP Buffer" temporary;
    begin
        TempJobWIPBuffer.Init();
        TempJobWIPBuffer.Insert();
        TempSalesLine.Init();
        TempSalesLine.Insert();
    end;
}
