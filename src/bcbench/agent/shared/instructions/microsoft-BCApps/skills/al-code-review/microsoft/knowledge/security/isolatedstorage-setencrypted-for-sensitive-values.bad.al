codeunit 50218 "Sec Sample SetEncrypted Bad"
{
    internal procedure StoreApiKey(ApiKeyValue: Text)
    begin
        IsolatedStorage.Set('ApiKey', ApiKeyValue, DataScope::Module);
    end;
}
