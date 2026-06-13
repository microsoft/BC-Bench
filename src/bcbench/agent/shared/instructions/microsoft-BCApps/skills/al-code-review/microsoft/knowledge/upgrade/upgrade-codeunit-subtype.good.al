codeunit 50200 "Upgrade My Feature"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeMyFeature();
    end;

    trigger OnUpgradePerDatabase()
    begin
        UpgradeMyGlobalSetup();
    end;

    local procedure UpgradeMyFeature() begin end;
    local procedure UpgradeMyGlobalSetup() begin end;
}
