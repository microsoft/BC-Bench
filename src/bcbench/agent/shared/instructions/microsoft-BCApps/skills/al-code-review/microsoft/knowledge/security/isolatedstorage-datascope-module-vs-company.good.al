codeunit 50219 "Sec Sample DataScope Good"
{
    internal procedure StoreTenantApiKey(ApiKey: Text)
    begin
        IsolatedStorage.SetEncrypted('TenantApiKey', ApiKey, DataScope::Module);
    end;

    internal procedure StoreCompanyWebhook(WebhookUrl: Text)
    begin
        IsolatedStorage.SetEncrypted('WebhookUrl', WebhookUrl, DataScope::Company);
    end;

    local procedure ReadCompanyWebhook(var WebhookUrl: SecretText): Boolean
    begin
        if not IsolatedStorage.Contains('WebhookUrl', DataScope::Company) then
            exit(false);
        IsolatedStorage.Get('WebhookUrl', DataScope::Company, WebhookUrl);
        exit(true);
    end;
}
