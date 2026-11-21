# [Event Request] codeunit 5763 "Whse.-Post Shipment" - PostUpdateWhseDocuments procedure

### Why do you need this change?

Dear support, In codeunit **5763 "Whse.-Post Shipment"**, we need an event that allows us to modify the filters for _WhseShptLine2_ and handle the underlying if statement, one of our clients had an implementation for this in Navision and we need to replicate it in BC.

### Describe the request

	[IntegrationEvent(false, false)]
	local procedure OnPostUpdateWhseDocumentsOnAfterWhseShptLineSetFilters(var WhseShptLine2: Record "Warehouse Shipment Line"; var WhsePostParameters: Record "Whse. Post Parameters")
	begin
	end;

[Changes between **]

	procedure PostUpdateWhseDocuments(var WhseShptHeaderParam: Record "Warehouse Shipment Header")
    var
        WhseShptLine2: Record "Warehouse Shipment Line";
        DeleteWhseShptLine: Boolean;
    begin
        OnBeforePostUpdateWhseDocuments(WhseShptHeaderParam, TempWarehouseShipmentLine);
        if TempWarehouseShipmentLine.Find('-') then begin
            repeat
                WhseShptLine2.Get(TempWarehouseShipmentLine."No.", TempWarehouseShipmentLine."Line No.");
                DeleteWhseShptLine := TempWarehouseShipmentLine."Qty. Outstanding" = TempWarehouseShipmentLine."Qty. to Ship";
                OnBeforeDeleteUpdateWhseShptLine(WhseShptLine2, DeleteWhseShptLine, TempWarehouseShipmentLine);
                if DeleteWhseShptLine then begin
                    ItemTrackingMgt.SetDeleteReservationEntries(true);
                    ItemTrackingMgt.DeleteWhseItemTrkgLines(
                      Database::"Warehouse Shipment Line", 0, TempWarehouseShipmentLine."No.", '', 0, TempWarehouseShipmentLine."Line No.", TempWarehouseShipmentLine."Location Code", true);
                    WhseShptLine2.Delete();
                    OnPostUpdateWhseDocumentsOnAfterWhseShptLine2Delete(WhseShptLine2);
                end else
                    UpdateWhseShptLine(WhseShptLine2, WhseShptHeaderParam);
            until TempWarehouseShipmentLine.Next() = 0;
            TempWarehouseShipmentLine.DeleteAll();

            OnPostUpdateWhseDocumentsOnAfterWhseShptLineBufLoop(WhseShptHeaderParam, WhseShptLine2, TempWarehouseShipmentLine);
        end;

        OnPostUpdateWhseDocumentsOnBeforeUpdateWhseShptHeader(WhseShptHeaderParam);

        WhseShptLine2.SetRange("No.", WhseShptHeaderParam."No.");
		** OnPostUpdateWhseDocumentsOnAfterWhseShptLineSetFilters(WhseShptLine2, WhseShptHeaderParam); **
        if WhseShptLine2.IsEmpty() then begin
            WhseShptHeaderParam.DeleteRelatedLines();
            WhseShptHeaderParam.Delete();
        end else begin
            WhseShptHeaderParam."Document Status" := WhseShptHeaderParam.GetShipmentStatus(0);
            if WhseShptHeaderParam."Create Posted Header" then begin
                WhseShptHeaderParam."Last Shipping No." := WhseShptHeaderParam."Shipping No.";
                WhseShptHeaderParam."Shipping No." := '';
                WhseShptHeaderParam."Create Posted Header" := false;
            end;
            OnPostUpdateWhseDocumentsOnBeforeWhseShptHeaderParamModify(WhseShptHeaderParam, WhseShptHeader);
            WhseShptHeaderParam.Modify();
        end;

        OnAfterPostUpdateWhseDocuments(WhseShptHeaderParam);
    end;
