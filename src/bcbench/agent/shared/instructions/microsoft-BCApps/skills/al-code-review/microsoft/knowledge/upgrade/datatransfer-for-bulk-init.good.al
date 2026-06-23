codeunit 50218 "Upgrade Price List Source"
{
    Subtype = Upgrade;

    local procedure UpdatePriceSourceGroupInPriceListLines()
    var
        PriceListLine: Record "Price List Line";
        PriceListLineDataTransfer: DataTransfer;
    begin
        PriceListLineDataTransfer.SetTables(Database::"Price List Line", Database::"Price List Line");
        PriceListLineDataTransfer.AddSourceFilter(
            PriceListLine.FieldNo("Source Group"), '=%1', "Price Source Group"::All);
        PriceListLineDataTransfer.AddSourceFilter(
            PriceListLine.FieldNo("Source Type"), '%1|%2|%3',
            "Price Source Type"::"All Jobs",
            "Price Source Type"::Job,
            "Price Source Type"::"Job Task");
        PriceListLineDataTransfer.AddConstantValue(
            "Price Source Group"::Job, PriceListLine.FieldNo("Source Group"));
        PriceListLineDataTransfer.CopyFields();
        Clear(PriceListLineDataTransfer);
    end;
}
