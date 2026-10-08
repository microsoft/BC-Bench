# [Event Request] table 36 "Sales Header" - OnCheckWhseShippingAdviceOnAfterSetLineFilters

### Why do you need this change?

We would like to apply custom filters to `SalesLine2` inside the `CheckShippingAdvice()` in "Sales Header" table.

### Describe the request

Hi Microsoft BC Dev Team,

Could you add this integration event `OnCheckWhseShippingAdviceOnAfterSetLineFilters` to table 36 "Sales Header"?

```diff
    procedure SynchronizeAsmHeader()
    var
        AsmHeader: Record "Assembly Header";
        ATOLink: Record "Assemble-to-Order Link";
        Window: Dialog;
    begin
        ATOLink.SetCurrentKey(Type, "Document Type", "Document No.");
        ATOLink.SetRange(Type, ATOLink.Type::Sale);
        ATOLink.SetRange("Document Type", "Document Type");
        ATOLink.SetRange("Document No.", "No.");
        if ATOLink.FindSet() then
            repeat
                if AsmHeader.Get(ATOLink."Assembly Document Type", ATOLink."Assembly Document No.") then
                    if "Posting Date" <> AsmHeader."Posting Date" then begin
                        Window.Open(StrSubstNo(SynchronizingMsg, "No.", AsmHeader."No."));
                        AsmHeader.Validate("Posting Date", "Posting Date");
                        AsmHeader.Modify();
                        Window.Close();
                    end;
            until ATOLink.Next() = 0;
    end;

    procedure CheckShippingAdvice()
    var
        SalesLine2: Record "Sales Line";
        Item: Record Item;
        QtyToShipBaseTotal: Decimal;
        Result: Boolean;
        IsHandled: Boolean;
    begin
        IsHandled := false;
        OnBeforeCheckShippingAdvice(Rec, IsHandled);
        if IsHandled then
            exit;

        SalesLine2.SetRange("Document Type", "Document Type");
        SalesLine2.SetRange("Document No.", "No.");
        SalesLine2.SetRange("Drop Shipment", false);
        SalesLine2.SetRange(Type, SalesLine.Type::Item);
+       OnCheckWhseShippingAdviceOnAfterSetLineFilters(SalesLine, SalesHeader);
        Result := true;
        if SalesLine2.FindSet() then
            repeat
                Item.Get(SalesLine2."No.");
                if SalesLine2.IsShipment() and (Item.Type = Item.Type::Inventory) then begin
                    QtyToShipBaseTotal += SalesLine2."Qty. to Ship (Base)";
                    if SalesLine2."Quantity (Base)" <>
                       SalesLine2."Qty. to Ship (Base)" + SalesLine2."Qty. Shipped (Base)"
                    then
                        Result := false;
                end;
            until SalesLine2.Next() = 0;
        if QtyToShipBaseTotal = 0 then
            Result := true;

        OnAfterCheckShippingAdvice(Rec, Result);
        if not Result then
            Error(ErrorInfo.Create(ShippingAdviceErr, true, Rec));
    end;

    protected procedure GetContactAsCompany(Contact: Record Contact; var SearchContact: Record Contact): Boolean;
    var
        IsHandled: Boolean;
    begin
        OnBeforeGetContactAsCompany(Contact, SearchContact, IsHandled);
        if not IsHandled then
            if Contact."Company No." <> '' then
                exit(SearchContact.Get(Contact."Company No."));
    end;
```

```
  [IntegrationEvent(false, false)]
  internal procedure OnCheckWhseShippingAdviceOnAfterSetLineFilters(var SalesLine: Record "Sales Line"; SalesHeader: Record "Sales Header")
  begin
  end;
```

Regards,
Jason
