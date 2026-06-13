codeunit 50204 "Sample Locked Label Good"
{
    var
        GetMethodTok: Label 'GET', Locked = true;
        ContentTypeJsonTok: Label 'application/json', Locked = true;
        ApiBaseUrlTok: Label 'https://api.contoso.com/v1', Locked = true;
        TelemetryStartTxt: Label 'Operation started for %1.', Locked = true;
}
