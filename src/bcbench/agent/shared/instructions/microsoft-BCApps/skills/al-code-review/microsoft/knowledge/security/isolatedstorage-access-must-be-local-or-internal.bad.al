codeunit 50216 "Sec Sample IsoStorage Bad"
{
    procedure GetApiKey(): Text
    var
        ApiKey: Text;
    begin
        if IsolatedStorage.Contains('ApiKey', DataScope::Module) then
            IsolatedStorage.Get('ApiKey', DataScope::Module, ApiKey);
        exit(ApiKey);
    end;

    procedure SetApiKey(NewKey: Text)
    begin
        IsolatedStorage.SetEncrypted('ApiKey', NewKey, DataScope::Module);
    end;
}
