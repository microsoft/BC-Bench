codeunit 50213 "Upgrade Tag Registration"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        UpgradeTag: Codeunit "Upgrade Tag";
    begin
        if UpgradeTag.HasUpgradeTag(MyUpgradeTag()) then
            exit;
        UpgradeTag.SetUpgradeTag(MyUpgradeTag());
    end;

    local procedure MyUpgradeTag(): Code[250]
    begin
        exit('MS-123456-MyFeature-20240101');
    end;

    // No OnGetPerCompanyUpgradeTags subscriber — the tag is unknown to the platform.
}
