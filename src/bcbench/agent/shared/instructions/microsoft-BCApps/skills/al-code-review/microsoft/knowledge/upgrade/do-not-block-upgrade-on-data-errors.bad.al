codeunit 50207 "Upgrade Graceful"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeCustomerLink('C00010');
    end;

    local procedure UpgradeCustomerLink(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        // Throws if the record is missing — aborts the upgrade.
        Customer.Get(CustomerNo);
    end;
}
