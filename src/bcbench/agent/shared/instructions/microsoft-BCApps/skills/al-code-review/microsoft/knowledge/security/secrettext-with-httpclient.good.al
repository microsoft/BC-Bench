codeunit 50209 "Sec Sample SecretHttp Good"
{
    procedure CallApiWithSecretUri(ApiKey: SecretText)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        SecretUri: SecretText;
    begin
        SecretUri := SecretStrSubstNo('https://api.example.com/data?key=%1', ApiKey);
        HttpClient.SetSecretRequestUri(SecretUri);
        HttpClient.Get('', Response);
    end;

    procedure CallApiWithBearer(BearerToken: SecretText)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        Headers: HttpHeaders;
        AuthHeader: SecretText;
    begin
        AuthHeader := SecretStrSubstNo('Bearer %1', BearerToken);
        Headers := HttpClient.DefaultRequestHeaders();
        Headers.Add('Authorization', AuthHeader);
        if not Headers.ContainsSecret('Authorization') then
            Error('Authorization header missing');
        HttpClient.Get('https://api.example.com/data', Response);
    end;
}
