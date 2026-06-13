codeunit 50201 "Upgrade My Feature"
{
    // Missing Subtype = Upgrade; the OnUpgrade trigger is never dispatched.
    trigger OnUpgradePerCompany()
    begin
        UpgradeMyFeature();
    end;

    local procedure UpgradeMyFeature() begin end;
}
