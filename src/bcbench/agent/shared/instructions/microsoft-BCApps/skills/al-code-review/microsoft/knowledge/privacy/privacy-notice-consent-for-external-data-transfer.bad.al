codeunit 50217 "Privacy Sample Consent Bad"
{
    procedure SendDataToExternalService(Customer: Record Customer)
    var
        HttpClient: HttpClient;
        Content: HttpContent;
        Response: HttpResponseMessage;
    begin
        Content.WriteFrom(StrSubstNo('{"email":"%1","name":"%2"}',
            Customer."E-Mail", Customer.Name));
        HttpClient.Post('https://api.externalservice.com/sync', Content, Response);
    end;
}
