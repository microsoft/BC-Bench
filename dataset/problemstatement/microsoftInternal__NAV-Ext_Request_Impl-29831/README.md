# [Event Request] Tableextension 99000860 "Mfg. Requisition Line".ValidateProdOrderOnReqLine

### Why do you need this change?


We need skip standard check logic. Main reason is skip ÃŽâ€œÃƒÂ¶Ã‚Â¼ÃŽâ€œÃƒÂ¶ÃƒÂ±ProdOrder.TestField(Blocked, false);ÃŽâ€œÃƒÂ¶Ã‚Â¼ÃŽâ€œÃƒÂ¶ÃƒÂ±, because in our workflow the order is set as blocked.
There is now another option how to skip standard logic and actual process block validation.

Our event is similar to existing event in  '"tableextension 99000751 "Mfg. Purchase Line" extends "Purchase Line"'

```al
    procedure ValidateProdOrderOnPurchLine()
    var
        Item: Record Item;
        ProdOrder: Record Microsoft.Manufacturing.Document."Production Order";
        ProdOrderLine: Record Microsoft.Manufacturing.Document."Prod. Order Line";
#if not CLEAN27
        AddonIntegrManagement: Codeunit Microsoft.Inventory.AddOnIntegrManagement;
#endif
        IsHandled: Boolean;
    begin
        IsHandled := false;
        OnBeforeValidateProdOrderOnPurchLine(Rec, IsHandled);
#if not CLEAN27
        AddonIntegrManagement.RunOnBeforeValidateProdOrderOnPurchLine(Rec, IsHandled);
#endif
        if IsHandled then
            exit;

        TestField(Type, Type::Item);

        if ProdOrder.Get(ProdOrder.Status::Released, "Prod. Order No.") then begin
            ProdOrder.TestField(Blocked, false);
            ProdOrderLine.SetRange(Status, ProdOrderLine.Status::Released);
            ProdOrderLine.SetRange("Prod. Order No.", "Prod. Order No.");
            ProdOrderLine.SetRange("Item No.", "No.");
            if ProdOrderLine.FindFirst() then
                "Routing No." := ProdOrderLine."Routing No.";
            Item.Get("No.");
            Validate("Unit of Measure Code", Item."Base Unit of Measure");
        end;
    end;
```

### Describe the request

```al
procedure ValidateProdOrderOnReqLine(var ReqLine: Record "Requisition Line")
var
    Item: Record Item;
    ProdOrder: Record "Production Order";
    ProdOrderLine: Record "Prod. Order Line";
    //------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:BEGIN
    IsHandled: Boolean;
    //------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:END
begin
    //------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:BEGIN
    IsHandled := false;
    OnBeforeValidateProdOrderOnReqLine(ReqLine, IsHandled);
    if IsHandled then
        exit;
    //------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:END

    ReqLine.TestField(Type, ReqLine.Type::Item);

    if ProdOrder.Get(ProdOrder.Status::Released, ReqLine."Prod. Order No.") then begin
        ProdOrder.TestField(Blocked, false);
        ProdOrderLine.SetRange(Status, ProdOrderLine.Status::Released);
        ProdOrderLine.SetRange("Prod. Order No.", ReqLine."Prod. Order No.");
        ProdOrderLine.SetRange("Item No.", ReqLine."No.");
        if ProdOrderLine.FindFirst() then begin
            ReqLine."Routing No." := ProdOrderLine."Routing No.";
            ReqLine."Routing Reference No." := ProdOrderLine."Line No.";
            ReqLine."Prod. Order Line No." := ProdOrderLine."Line No.";
            ReqLine."Requester ID" := CopyStr(UserId(), 1, MaxStrLen(ReqLine."Requester ID"));
        end;
        Item.Get(ReqLine."No.");
        ReqLine.Validate("Unit of Measure Code", Item."Base Unit of Measure");
    end;
end;

//------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:BEGIN
[IntegrationEvent(false, false)]
local procedure OnBeforeValidateProdOrderOnReqLine(var ReqLine: Record "Requisition Line"; var IsHandled: Boolean)
begin
end;
//------------------------------------------------------------OnBeforeValidateProdOrderOnReqLine:END
```
