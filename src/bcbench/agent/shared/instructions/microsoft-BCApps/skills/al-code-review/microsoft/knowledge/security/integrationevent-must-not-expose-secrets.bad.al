codeunit 50229 "Sec Sample EventSecret Bad"
{
    [IntegrationEvent(false, false)]
    local procedure OnBeforeSendRequest(var ApiKey: Text; var Password: Text; var RequestUrl: Text)
    begin
    end;
}
