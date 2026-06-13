codeunit 50257 "Perf Sample EventGuard Bad"
{
    [EventSubscriber(ObjectType::Table, Database::"Sales Line", 'OnAfterValidateEvent', 'Quantity', false, false)]
    local procedure OnAfterValidateQuantity(var Rec: Record "Sales Line")
    var
        Item: Record Item;
    begin
        // Item.Get fires on every Quantity edit — including lines whose Type is
        // not Item. No cheap guard, no SetLoadFields.
        Item.Get(Rec."No.");
        if Item."Item Category Code" <> '' then
            RecalculatePrice(Rec, Item);
    end;

    local procedure RecalculatePrice(var SalesLine: Record "Sales Line"; var Item: Record Item)
    begin
    end;
}
