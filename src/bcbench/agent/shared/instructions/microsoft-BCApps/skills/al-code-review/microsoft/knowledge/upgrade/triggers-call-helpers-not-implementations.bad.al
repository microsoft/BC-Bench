codeunit 50203 "Upgrade Orchestrator"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        Customer: Record Customer;
    begin
        // Direct implementation in the trigger body — wrong.
        Customer.ModifyAll("Some Field", true);
    end;
}
