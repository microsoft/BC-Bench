codeunit 50222 "Sec Sample UrlValidation Bad"
{
    procedure SyncWithExternalService(ServiceUrl: Text)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
    begin
        HttpClient.Get(ServiceUrl, Response);
    end;

    procedure SendWebhookNotification(CallbackUrl: Text; Payload: Text)
    var
        HttpClient: HttpClient;
        Content: HttpContent;
        Response: HttpResponseMessage;
    begin
        Content.WriteFrom(Payload);
        HttpClient.Post(CallbackUrl, Content, Response);
    end;
}
