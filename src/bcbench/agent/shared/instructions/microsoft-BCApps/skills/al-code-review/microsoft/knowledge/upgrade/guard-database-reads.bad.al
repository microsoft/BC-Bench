codeunit 50205 "Upgrade Guarded Reads"
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
        Item.Get('1000');     // Throws if missing; aborts upgrade.
        Customer.FindSet();   // Throws if empty.
        Vendor.FindLast();    // Throws if empty.
    end;
}
