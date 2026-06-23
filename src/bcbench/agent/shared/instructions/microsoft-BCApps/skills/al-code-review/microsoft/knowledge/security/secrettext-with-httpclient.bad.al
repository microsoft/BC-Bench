codeunit 50210 "Sec Sample SecretHttp Bad"
{
    procedure CallApiWithSecretInUri(ApiKey: SecretText)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        RequestUri: Text;
    begin
        RequestUri := 'https://api.example.com/data?key=' + ApiKey.Unwrap();
        HttpClient.Get(RequestUri, Response);
    end;

    procedure CallApiWithBearer(BearerToken: SecretText)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        Headers: HttpHeaders;
    begin
        Headers := HttpClient.DefaultRequestHeaders();
        Headers.Add('Authorization', 'Bearer ' + BearerToken.Unwrap());
        HttpClient.Get('https://api.example.com/data', Response);
    end;
}
