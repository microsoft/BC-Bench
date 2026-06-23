codeunit 50219 "Upgrade Price List Source"
{
    Subtype = Upgrade;

    local procedure UpdatePriceSourceGroupInPriceListLines()
    var
        PriceListLine: Record "Price List Line";
    begin
        // One round-trip per row across a potentially large table.
        PriceListLine.SetRange("Source Group", "Price Source Group"::All);
        if PriceListLine.FindSet(true) then
            repeat
                if PriceListLine."Source Type" in
                    ["Price Source Type"::"All Jobs",
                     "Price Source Type"::Job,
                     "Price Source Type"::"Job Task"]
                then begin
                    PriceListLine."Source Group" := "Price Source Group"::Job;
                    PriceListLine.Modify();
                end;
            until PriceListLine.Next() = 0;
    end;
}
