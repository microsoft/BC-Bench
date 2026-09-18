# [Global Request] Codeunit 333 "Req. Wksh.-Make Order"

### Why do you need this change?

Problem statement:
We provide to customer option where they can change series nos for TranferHeader. Problem is that procedure for SetTransferHeader is local we would like call function from different object. Please make functions as global.

### Describe the request

```al
//local procedure GetTransferHeader(var TransferHeader: Record "Transfer Header"; RequisitionLine: Record "Requisition Line")
procedure GetTransferHeader(var TransferHeader: Record "Transfer Header"; RequisitionLine: Record "Requisition Line")
begin
    TempTransHeader.SetRange("Transfer-from Code", RequisitionLine."Transfer-from Code");
    TempTransHeader.SetRange("Transfer-to Code", RequisitionLine."Location Code");
    if TempTransHeader.FindFirst() then
        TransferHeader.Get(TempTransHeader."No.");
end;

//local procedure SetTransferHeader(TransferHeader: Record "Transfer Header")
procedure SetTransferHeader(TransferHeader: Record "Transfer Header")
begin
    TempTransHeader := TransferHeader;
    if TempTransHeader.Insert() then;
end;
```
