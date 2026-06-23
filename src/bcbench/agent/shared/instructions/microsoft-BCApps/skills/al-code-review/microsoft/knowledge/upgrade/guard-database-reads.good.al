codeunit 50204 "Upgrade Guarded Reads"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeMyFeature();
    end;

    local procedure UpgradeMyFeature()
    var
        Item: Record Item;
        Customer: Record Customer;
        Vendor: Record Vendor;
    begin
        if Item.Get('1000') then
            Item.Modify();
        if Customer.FindSet() then;
        if not Vendor.FindLast() then
            exit;
    end;
}
