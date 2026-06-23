codeunit 50209 "Upgrade Tag Driven"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        AppInfo: ModuleInfo;
    begin
        NavApp.GetCurrentModuleInfo(AppInfo);

        // Version-coupled branching — breaks when a tenant skips a version.
        if AppInfo.DataVersion().Major > 14 then
            exit;

        if AppInfo.DataVersion().Major < 14 then
            UpgradeFeatureA()
        else if AppInfo.DataVersion().Major < 17 then
            UpgradeFeatureB()
        else
            exit;
    end;

    local procedure UpgradeFeatureA() begin end;
    local procedure UpgradeFeatureB() begin end;
}
