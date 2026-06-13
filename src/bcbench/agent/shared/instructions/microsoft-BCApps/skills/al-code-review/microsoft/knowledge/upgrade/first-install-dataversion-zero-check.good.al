codeunit 50210 "Install My Extension"
{
    Subtype = Install;

    trigger OnInstallAppPerCompany()
    var
        AppInfo: ModuleInfo;
    begin
        NavApp.GetCurrentModuleInfo(AppInfo);
        if AppInfo.DataVersion() <> Version.Create('0.0.0.0') then
            exit;

        // Install-only seed code goes here.
    end;
}
