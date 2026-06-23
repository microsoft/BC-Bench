codeunit 50216 "Privacy Sample Consent Good"
{
    procedure SendDataToExternalService(Customer: Record Customer)
    var
        PrivacyNotice: Codeunit "Privacy Notice";
        PrivacyNoticeRegistrations: Codeunit "Privacy Notice Registrations";
        HttpClient: HttpClient;
        Content: HttpContent;
        Response: HttpResponseMessage;
        PrivacyConsentRequiredErr: Label 'Privacy notice consent is required for this integration.';
    begin
        if PrivacyNotice.GetPrivacyNoticeApprovalState(
            PrivacyNoticeRegistrations.GetExchangePrivacyNoticeId())
            <> "Privacy Notice Approval State"::Agreed
        then
            Error(PrivacyConsentRequiredErr);

        Content.WriteFrom(StrSubstNo('{"email":"%1","name":"%2"}',
            Customer."E-Mail", Customer.Name));
        HttpClient.Post('https://api.externalservice.com/sync', Content, Response);
    end;
}
