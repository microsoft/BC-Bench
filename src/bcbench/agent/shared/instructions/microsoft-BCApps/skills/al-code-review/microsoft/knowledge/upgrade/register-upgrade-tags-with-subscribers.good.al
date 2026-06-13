codeunit 50212 "Upgrade Tag Registration"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        UpgradeTag: Codeunit "Upgrade Tag";
    begin
        if UpgradeTag.HasUpgradeTag(MyUpgradeTag()) then
            exit;
        // Upgrade work ...
        UpgradeTag.SetUpgradeTag(MyUpgradeTag());
    end;

    local procedure MyUpgradeTag(): Code[250]
    begin
        exit('MS-123456-MyFeature-20240101');
    end;

    [EventSubscriber(ObjectType::Codeunit, Codeunit::"Upgrade Tag", 'OnGetPerCompanyUpgradeTags', '', false, false)]
    local procedure RegisterPerCompanyTags(var PerCompanyUpgradeTags: List of [Code[250]])
    begin
        PerCompanyUpgradeTags.Add(MyUpgradeTag());
    end;
}
