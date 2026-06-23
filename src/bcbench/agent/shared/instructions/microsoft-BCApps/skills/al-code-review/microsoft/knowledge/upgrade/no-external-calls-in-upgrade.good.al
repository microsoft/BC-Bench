codeunit 50214 "Upgrade No External"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        ExternalSyncSetup: Record "External Sync Setup";
    begin
        // Defer the external call: just set a flag the runtime path will pick up.
        if not ExternalSyncSetup.Get() then begin
            ExternalSyncSetup.Init();
            ExternalSyncSetup.Insert();
        end;
        ExternalSyncSetup."Resync Required" := true;
        ExternalSyncSetup.Modify();
    end;
}
