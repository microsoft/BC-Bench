# Expose CheckWhseRequest() procedure from Report 7323 "Create Invt Put-away/Pick/Mvmt"

### Why do you need this change?

We would like to customise Inventory Putaway creation process so would need to call local procedure `CheckWhseRequest()` from outside of "Create Invt Put-away/Pick/Mvmt" report.

### Describe the request

Hi Microsoft BC Dev Team,

Could you expose the  `CheckWhseRequest()` in Report 7323 "Create Invt Put-away/Pick/Mvmt" to public? Currently it is set as a local procedure.

```
  local procedure CheckWhseRequest(var WarehouseRequest: Record "Warehouse Request") SkipRecord: Boolean
  var
      SalesHeader: Record "Sales Header";
      TransferHeader: Record "Transfer Header";
      GetSrcDocOutbound: Codeunit "Get Source Doc. Outbound";
      IsHandled: Boolean;
  begin
      IsHandled := false;
      OnBeforeCheckWhseRequest(WarehouseRequest, ShowError, SkipRecord, IsHandled);
      if IsHandled then
          exit(SkipRecord);
      if WarehouseRequest."Document Status" <> WarehouseRequest."Document Status"::Released then
          SkipRecord := true
      else
          if (WarehouseRequest.Type = WarehouseRequest.Type::Outbound) and
              (WarehouseRequest."Shipping Advice" = WarehouseRequest."Shipping Advice"::Complete)
          then
              case WarehouseRequest."Source Type" of
                  Database::"Sales Line":
                      if WarehouseRequest."Source Subtype" = WarehouseRequest."Source Subtype"::"1" then begin
                          SkipRecord := not SalesHeader.Get(SalesHeader."Document Type"::Order, WarehouseRequest."Source No.");
                          if not SkipRecord then
                              SkipRecord := GetSrcDocOutbound.CheckSalesHeader(SalesHeader, ShowError);
                      end;
                  Database::"Transfer Line":
                      begin
                          SkipRecord := not TransferHeader.Get(WarehouseRequest."Source No.");
                          if not SkipRecord then
                              SkipRecord := GetSrcDocOutbound.CheckTransferHeader(TransferHeader, ShowError);
                      end;
              end;
      OnAfterCheckWhseRequest(WarehouseRequest, SkipRecord);
  end;
```

Regards,
Jason
