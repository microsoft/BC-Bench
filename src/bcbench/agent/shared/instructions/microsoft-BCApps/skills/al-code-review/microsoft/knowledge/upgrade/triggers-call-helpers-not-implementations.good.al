codeunit 50202 "Upgrade Orchestrator"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeMyFeature();
        UpgradeSecondFeature();
    end;

    local procedure UpgradeMyFeature()
    var
        Customer: Record Customer;
    begin
        Customer.ModifyAll("Some Field", true);
    end;

    local procedure UpgradeSecondFeature() begin end;
}
