codeunit 50207 "Sec Sample SecretText Good"
{
    procedure CallExternalApi()
    var
        ApiKey: SecretText;
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        Headers: HttpHeaders;
    begin
        if IsolatedStorage.Contains('ApiKey', DataScope::Module) then
            IsolatedStorage.Get('ApiKey', DataScope::Module, ApiKey);
        Headers := HttpClient.DefaultRequestHeaders();
        Headers.Add('X-Api-Key', ApiKey);
        HttpClient.Get('https://api.example.com/data', Response);
    end;
}
