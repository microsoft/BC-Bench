codeunit 50252 "Perf Sample NPlus1 Good"
{
    procedure SumStdCost(var BOMLine: Record "BOM Component") TotalCost: Decimal
    var
        Item: Record Item;
    begin
        Item.SetLoadFields("Costing Method", "Standard Cost");
        if BOMLine.FindSet() then
            repeat
                if Item.Get(BOMLine."No.") then
                    if Item."Costing Method" = Item."Costing Method"::Standard then
                        TotalCost += Item."Standard Cost" * BOMLine."Quantity per";
            until BOMLine.Next() = 0;
    end;
}
