codeunit 50218 "Privacy Sample Register Integration"
{
    [EventSubscriber(ObjectType::Codeunit, Codeunit::"Privacy Notice Registrations", 'OnRegisterPrivacyNotices', '', false, false)]
    local procedure OnRegisterPrivacyNotices(var TempPrivacyNotice: Record "Privacy Notice" temporary)
    var
        PrivacyNotice: Codeunit "Privacy Notice";
    begin
        PrivacyNotice.CreatePrivacyNoticeForIntegration(
            'My External Sync', 'External Customer Sync Service');
    end;
}
