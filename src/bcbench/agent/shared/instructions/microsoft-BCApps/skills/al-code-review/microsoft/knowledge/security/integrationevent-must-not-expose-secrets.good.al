codeunit 50228 "Sec Sample EventSecret Good"
{
    [IntegrationEvent(false, false)]
    local procedure OnBeforeSendRequest(var RequestPayload: JsonObject; var IsHandled: Boolean)
    begin
    end;
}
