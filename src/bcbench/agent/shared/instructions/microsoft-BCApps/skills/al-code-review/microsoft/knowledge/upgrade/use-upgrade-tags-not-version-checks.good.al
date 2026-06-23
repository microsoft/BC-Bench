codeunit 50208 "Upgrade Tag Driven"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeMyFeature();
    end;

    local procedure UpgradeMyFeature()
    var
        UpgradeTag: Codeunit "Upgrade Tag";
    begin
        if UpgradeTag.HasUpgradeTag(MyUpgradeTag()) then
            exit;

        // Upgrade work goes here.

        UpgradeTag.SetUpgradeTag(MyUpgradeTag());
    end;

    local procedure MyUpgradeTag(): Code[250]
    begin
        exit('MS-123456-MyFeatureUpgrade-20240101');
    end;
}
