codeunit 50256 "Perf Sample EventGuard Good"
{
    [EventSubscriber(ObjectType::Table, Database::"Sales Line", 'OnAfterValidateEvent', 'Quantity', false, false)]
    local procedure OnAfterValidateQuantity(var Rec: Record "Sales Line")
    var
        Item: Record Item;
    begin
        if Rec.Type <> Rec.Type::Item then
            exit;
        Item.SetLoadFields("Item Category Code");
        if Item.Get(Rec."No.") then
            if Item."Item Category Code" <> '' then
                RecalculatePrice(Rec, Item);
    end;

    local procedure RecalculatePrice(var SalesLine: Record "Sales Line"; var Item: Record Item)
    begin
    end;
}
