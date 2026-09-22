# [Event Request] Codeunit 80 "Sales-Post" - Procedure SyncSurPlusItemTracking

### Why do you need this change?

Hi,
i need an event at the end of procedure "SyncSurPlusItemTracking" in the Codeunit 80 "Sales-Post" to skip the execution of the "ModifyAll".

We need the event because we have an app that creates reservation entries of type Surplus, but the standard procedure "SyncSurPlusItemTracking" zeroes out the "Qty. to Handle (Base)" and "Qty. to Invoice (Base)" on these entries.
This causes an error when posting the warehouse shipment.
Our app has its logic to decide when skip the execution of "ModifyAll".

Below is the standard procedure code:

`

               local procedure SyncSurPlusItemTracking(SalesHeader: Record "Sales Header"; SalesLine: Record "Sales Line")
    var
        Location2: Record Location;
        ReservEntry: Record "Reservation Entry";
        TempTrackingSpecification2: Record "Tracking Specification" temporary;
        TempWarehouseActivityLine: Record "Warehouse Activity Line" temporary;
        WarehouseAvailabilityMgt: Codeunit "Warehouse Availability Mgt.";
        QtyReservedForCurrLine: Decimal;
        SurplusQtyToHandle: Decimal;
    begin
        if not SalesHeader.Ship then
            exit;
        if not (SalesHeader."Document Type" in [SalesHeader."Document Type"::Invoice, SalesHeader."Document Type"::Order]) then
            exit;

        if (SalesLine."Location Code" = '') or
           not Location2.Get(SalesLine."Location Code") or
           not Location2."Require Shipment"
        then
            exit;

        TempTrackingSpecification2.SetSourceFromSalesLine(SalesLine);
        QtyReservedForCurrLine := Abs(WarehouseAvailabilityMgt.CalcLineReservedQtyOnInvt(
            TempTrackingSpecification2."Source Type", TempTrackingSpecification2."Source Subtype", TempTrackingSpecification2."Source ID", TempTrackingSpecification2."Source Ref. No.",
            0, false, TempWarehouseActivityLine));

        if QtyReservedForCurrLine = 0 then
            exit;

        ReservEntry.SetSourceFilter(
                                 TempTrackingSpecification2."Source Type", TempTrackingSpecification2."Source Subtype",
                                 TempTrackingSpecification2."Source ID", TempTrackingSpecification2."Source Ref. No.", true);
        ReservEntry.SetSourceFilter('', TempTrackingSpecification2."Source Prod. Order Line");
        ReservEntry.SetRange("Reservation Status", ReservEntry."Reservation Status"::Surplus);
        if not ReservEntry.FindSet() then
            exit;

        ReservEntry.CalcSums("Qty. to Handle (Base)");
        SurplusQtyToHandle := Abs(ReservEntry."Qty. to Handle (Base)");
        if (QtyReservedForCurrLine + SurplusQtyToHandle) < SalesLine."Qty. to Ship (Base)" then
            exit;

         ReservEntry.ModifyAll("Qty. to Handle (Base)", 0);
         ReservEntry.ModifyAll("Qty. to Invoice (Base)", 0);


    end;




`

### Describe the request

Add a new event at the end of procedure "SyncSurPlusItemTracking" in the Codeunit 80 "Sales-Post" to skip the execution of the "ModifyAll".

`

               local procedure SyncSurPlusItemTracking(SalesHeader: Record "Sales Header"; SalesLine: Record "Sales Line")
    var
        Location2: Record Location;
        ReservEntry: Record "Reservation Entry";
        TempTrackingSpecification2: Record "Tracking Specification" temporary;
        TempWarehouseActivityLine: Record "Warehouse Activity Line" temporary;
        WarehouseAvailabilityMgt: Codeunit "Warehouse Availability Mgt.";
        QtyReservedForCurrLine: Decimal;
        SurplusQtyToHandle: Decimal;
        IsHandled: Boolean;
    begin
        if not SalesHeader.Ship then
            exit;
        if not (SalesHeader."Document Type" in [SalesHeader."Document Type"::Invoice, SalesHeader."Document Type"::Order]) then
            exit;

        if (SalesLine."Location Code" = '') or
           not Location2.Get(SalesLine."Location Code") or
           not Location2."Require Shipment"
        then
            exit;

        TempTrackingSpecification2.SetSourceFromSalesLine(SalesLine);
        QtyReservedForCurrLine := Abs(WarehouseAvailabilityMgt.CalcLineReservedQtyOnInvt(
            TempTrackingSpecification2."Source Type", TempTrackingSpecification2."Source Subtype", TempTrackingSpecification2."Source ID", TempTrackingSpecification2."Source Ref. No.",
            0, false, TempWarehouseActivityLine));

        if QtyReservedForCurrLine = 0 then
            exit;

        ReservEntry.SetSourceFilter(
                                 TempTrackingSpecification2."Source Type", TempTrackingSpecification2."Source Subtype",
                                 TempTrackingSpecification2."Source ID", TempTrackingSpecification2."Source Ref. No.", true);
        ReservEntry.SetSourceFilter('', TempTrackingSpecification2."Source Prod. Order Line");
        ReservEntry.SetRange("Reservation Status", ReservEntry."Reservation Status"::Surplus);
        if not ReservEntry.FindSet() then
            exit;

        ReservEntry.CalcSums("Qty. to Handle (Base)");
        SurplusQtyToHandle := Abs(ReservEntry."Qty. to Handle (Base)");
        if (QtyReservedForCurrLine + SurplusQtyToHandle) < SalesLine."Qty. to Ship (Base)" then
            exit;


        // New Event with IsHandled

           OnBeforeModifyQtyToHandleInvoiceOnAfterSyncSurPlusItemTracking(SalesLine, SalesHeader, IsHandled, ReservEntry);

          if not IsHandled then begin

                 ReservEntry.ModifyAll("Qty. to Handle (Base)", 0);
                 ReservEntry.ModifyAll("Qty. to Invoice (Base)", 0);
        end;

    end;




`




`

          [IntegrationEvent(false, false)]
    local procedure OnBeforeModifyQtyToHandleInvoiceOnAfterSyncSurPlusItemTracking(SalesLine: Record "Sales Line"; SalesHeader: Record "Sales Header"; var IsHandled: Boolean; var ReservEntry: Record "Reservation Entry")
    begin
    end;



`
