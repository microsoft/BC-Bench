# [Event Request] codeunit 333 "Req. Wksh.-Make Order" - TryCarryOutReqLineAction procedure

### Why do you need this change?

Dear support, in codeunit **333 "Req. Wksh.-Make Order"** we need two events: one to set additional parameters before calling `ReqWkshMakeOrders.Run(ReqLine)`, and the second to retrieve the parameter values after the call.

I added `IsHandled` in the first event just in case someone wanted to handle the call differently, but for my purposes it isn't really necessary.

Inserting the event before `ReqWkshMakeOrders.Run(ReqLine)` is just a matter of order; in fact, `OnBeforeTryCarryOutReqLineAction` would work, but it's missing the `ReqWkshMakeOrders` parameter, so I wouldn't be able to perform the operations there.

### Describe the request

	[IntegrationEvent(false, false)]
    local procedure OnTryCarryOutReqLineActionOnBeforeRun(var ReqWkshMakeOrders: Codeunit "Req. Wksh.-Make Order"; var ReqLine: Record "Requisition Line"; var IsHandled: Boolean; var Result: Boolean)
    begin
    end;

	[IntegrationEvent(false, false)]
    local procedure OnTryCarryOutReqLineActionOnAfterGetTryParam(var ReqWkshMakeOrders: Codeunit "Req. Wksh.-Make Order")
    begin
    end;

[Changes between **]

	local procedure TryCarryOutReqLineAction(var ReqLine: Record "Requisition Line"): Boolean
	var
		**
		IsHandled: Boolean;
		Result: Boolean;
		**
    begin
        OnBeforeTryCarryOutReqLineAction(ReqLine);

        ReqWkshMakeOrders.Set(PurchOrderHeader, EndOrderDate, PrintPurchOrders);
        ReqWkshMakeOrders.SetTryParam(
          ReqTemplate,
          LineCount,
          NextLineNo,
          PrevPurchCode,
          PrevShipToCode,
          PrevLocationCode,
          OrderCounter,
          OrderLineCounter,
          TempFailedReqLine,
          TempDocumentEntry);
        ReqWkshMakeOrders.SetSuppressCommit(SuppressCommit);
		**
		IsHandled := false;
		Result := false;
		OnTryCarryOutReqLineActionOnBeforeRun(ReqWkshMakeOrders, ReqLine, IsHandled, Result);
		if IsHandled then
			exit(Result);
		**
        if ReqWkshMakeOrders.Run(ReqLine) then begin
            ReqWkshMakeOrders.GetTryParam(
              PurchOrderHeader,
              LineCount,
              NextLineNo,
              PrevPurchCode,
              PrevShipToCode,
              PrevLocationCode,
              OrderCounter,
              OrderLineCounter);

			** OnTryCarryOutReqLineActionOnAfterGetTryParam(ReqWkshMakeOrders); **

            if PrintPurchOrders and PlanningResiliency then
                if PurchOrderHeader."No." <> '' then
                    if not TempPurchaseOrderToPrint.Get(PurchOrderHeader."Document Type", PurchOrderHeader."No.") then begin
                        TempPurchaseOrderToPrint := PurchOrderHeader;
                        TempPurchaseOrderToPrint.Insert();
                    end;

            if not HideProgressWindow then begin
                Window.Update(3, OrderCounter);
                Window.Update(4, LineCount);
                Window.Update(5, OrderLineCounter);
            end;
            exit(true);
        end;
        exit(false)
    end;
