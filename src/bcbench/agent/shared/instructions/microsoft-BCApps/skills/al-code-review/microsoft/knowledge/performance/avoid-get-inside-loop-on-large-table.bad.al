codeunit 50253 "Perf Sample NPlus1 Bad"
{
    procedure SumStdCost(var BOMLine: Record "BOM Component") TotalCost: Decimal
    var
        Item: Record Item;
    begin
        if BOMLine.FindSet() then
            repeat
                // Full-row Item.Get per BOM line — no partial loading, no caching.
                Item.Get(BOMLine."No.");
                if Item."Costing Method" = Item."Costing Method"::Standard then
                    TotalCost += Item."Standard Cost" * BOMLine."Quantity per";
            until BOMLine.Next() = 0;
    end;
}
