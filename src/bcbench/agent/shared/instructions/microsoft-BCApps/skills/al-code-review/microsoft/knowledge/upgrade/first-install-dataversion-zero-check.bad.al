codeunit 50211 "Install My Extension"
{
    Subtype = Install;

    trigger OnInstallAppPerCompany()
    begin
        // No DataVersion() guard — this runs on every reinstall and upgrade
        // path, duplicating seed rows.
        SeedDefaultRows();
    end;

    local procedure SeedDefaultRows() begin end;
}
