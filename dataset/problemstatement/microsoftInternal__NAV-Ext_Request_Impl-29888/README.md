# page 2900 "Demand Forecast Variant Matrix" add a new Event OnBeforeLoadData in the procedure LoadData

### Why do you need this change?

```
local procedure LoadData(ItemFilter: Text; LocationFilter: Text; UseLocation: Boolean; UseVariant: Boolean; VariantFilter: Text)
    var
        Item: Record Item;
        SelectionFilterMgt: Codeunit SelectionFilterManagement;
        ItemWithVariantsAndLocationsQuery: Query "Item With Variants & Locations";
        ItemWithVariantsQuery: Query "Item With Variants";
        ItemWithLocationsQuery: Query "Item With Locations";
        EntryNo: Integer;
        IsHandled: Boolean;
    begin
        Rec.DeleteAll();
        EntryNo := 0;
        ShowVariants := UseVariant;
        ShowLocations := `UseLocation;`
        Item.SetView(ItemFilter);
        if Item.IsEmpty() then
            exit;

        //New Event ++
        OnBeforeLoadData(Rec, Item, ItemFilter, LocationFilter, UseLocation, UseVariant, VariantFilter, MaxRowsToLoadVal, IsHandled);
        if IsHandled then
            exit;
        //New Event --

        case GetQueryForMatrix(UseVariant, UseLocation) of
            Database::Item:
                begin
                    Item.SetRange(Type, Item.Type::Inventory);
                    if Item.FindSet() then
                        repeat
                            if not IncrementEntryNo(EntryNo) then
                                break;
                            Rec.Init();
                            Rec."Entry No." := EntryNo;
                            Rec."No." := Item."No.";
                            Rec.Description := Item.Description;
                            Rec.Insert();
                        until Item.Next() = 0;
                end;
            Query::"Item With Variants":
                begin
                    ItemWithVariantsQuery.SetFilter(No_, SelectionFilterMgt.GetSelectionFilterForItem(Item));
                    ItemWithVariantsQuery.SetFilter(VariantCode, VariantFilter);
                    ItemWithVariantsQuery.SetRange(Type, "Item Type"::Inventory);

                    if ItemWithVariantsQuery.Open() then
                        while ItemWithVariantsQuery.Read() do begin
                            if not IncrementEntryNo(EntryNo) then
                                break;
                            Rec.Init();
                            Rec."Entry No." := EntryNo;
                            Rec."No." := ItemWithVariantsQuery.No_;
                            Rec.Description := ItemWithVariantsQuery.Description;
                            Rec."Variant Code" := ItemWithVariantsQuery.VariantCode;
                            Rec."Variant Filter" := ItemWithVariantsQuery.VariantCode;
                            Rec.Insert();
                        end;
                    ItemWithVariantsQuery.Close();
                end;
            Query::"Item With Locations":
                begin
                    ItemWithLocationsQuery.SetFilter(No_, SelectionFilterMgt.GetSelectionFilterForItem(Item));
                    ItemWithLocationsQuery.SetFilter(LocationCode, LocationFilter);
                    ItemWithLocationsQuery.SetRange(Type, "Item Type"::Inventory);
                    ItemWithLocationsQuery.SetRange(Use_As_In_Transit, false);
                    if ItemWithLocationsQuery.Open() then
                        while ItemWithLocationsQuery.Read() do begin
                            if not IncrementEntryNo(EntryNo) then
                                break;
                            Rec.Init();
                            Rec."Entry No." := EntryNo;
                            Rec."No." := ItemWithLocationsQuery.No_;
                            Rec.Description := ItemWithLocationsQuery.Description;
                            Rec."Location Code" := ItemWithLocationsQuery.LocationCode;
                            Rec."Location Filter" := ItemWithLocationsQuery.LocationCode;
                            Rec.Insert();
                        end;
                    ItemWithLocationsQuery.Close();
                end;
            Query::"Item With Variants & Locations":
                begin
                    ItemWithVariantsAndLocationsQuery.SetFilter(No_, SelectionFilterMgt.GetSelectionFilterForItem(Item));
                    ItemWithVariantsAndLocationsQuery.SetFilter(LocationCode, LocationFilter);
                    ItemWithVariantsAndLocationsQuery.SetFilter(VariantCode, VariantFilter);
                    ItemWithVariantsAndLocationsQuery.SetRange(Type, "Item Type"::Inventory);
                    ItemWithVariantsAndLocationsQuery.SetRange(Use_As_In_Transit, false);
                    if ItemWithVariantsAndLocationsQuery.Open() then
                        while ItemWithVariantsAndLocationsQuery.Read() do begin
                            if not IncrementEntryNo(EntryNo) then
                                break;
                            Rec.Init();
                            Rec."Entry No." := EntryNo;
                            Rec."No." := ItemWithVariantsAndLocationsQuery.No_;
                            Rec.Description := ItemWithVariantsAndLocationsQuery.Description;
                            Rec."Variant Code" := ItemWithVariantsAndLocationsQuery.VariantCode;
                            Rec."Variant Filter" := ItemWithVariantsAndLocationsQuery.VariantCode;
                            Rec."Location Code" := ItemWithVariantsAndLocationsQuery.LocationCode;
                            Rec."Location Filter" := ItemWithVariantsAndLocationsQuery.LocationCode;
                            Rec.Insert();
                        end;
                    ItemWithVariantsAndLocationsQuery.Close();
                end;
        end;

        //Point to the first row of the matrix
        OnLoadDataOnBeforeRecFindFirst(Rec, ItemFilter, LocationFilter, UseLocation, UseVariant, VariantFilter);
        if not Rec.IsEmpty() then
            Rec.FindFirst();
    end;

   //New Event ++
    [IntegrationEvent(false, false)]
    local procedure OnBeforeLoadData(var ForecastItemVariantLoc: Record "Forecast Item Variant Loc"; var Item: Record Item; ItemFilter: Text; LocationFilter: Text; UseLocation: Boolean; UseVariant: Boolean; VariantFilter: Text; MaxRowsToLoadVal: Integer; var IsHandled: Boolean)
    begin
    end;
    //New Event --







```

### Describe the request

 Page 2900 "Demand Forecast Variant Matrix" add a new Event OnBeforeLoadData in the procedure LoadData
