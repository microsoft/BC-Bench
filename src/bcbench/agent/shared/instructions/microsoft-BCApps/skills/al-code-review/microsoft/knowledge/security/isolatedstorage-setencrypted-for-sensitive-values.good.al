codeunit 50217 "Sec Sample SetEncrypted Good"
{
    internal procedure StoreApiKey(ApiKeyValue: Text)
    begin
        if StrLen(ApiKeyValue) > 200 then
            Error('API key too long for encrypted storage');
        IsolatedStorage.SetEncrypted('ApiKey', ApiKeyValue, DataScope::Module);
    end;

    local procedure ReadApiKey(var ApiKey: SecretText): Boolean
    begin
        if not IsolatedStorage.Contains('ApiKey', DataScope::Module) then
            exit(false);
        IsolatedStorage.Get('ApiKey', DataScope::Module, ApiKey);
        exit(true);
    end;
}
