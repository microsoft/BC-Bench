codeunit 50215 "Upgrade No External"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    var
        Client: HttpClient;
        Response: HttpResponseMessage;
    begin
        // External call inside upgrade code — can hang or fail and abort the upgrade.
        Client.Get('https://external-service.contoso.com/api/sync', Response);
    end;
}
