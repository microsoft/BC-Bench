codeunit 50208 "Privacy Sample GetLastError Good"
{
    procedure AddAttachmentSafely()
    var
        AttachmentFailedErr: Label 'Failed to add email attachment. Please try again.';
    begin
        if not TryAddAttachment() then
            Error(AttachmentFailedErr);
    end;

    [TryFunction]
    local procedure TryAddAttachment()
    begin
        // ... attachment logic that may fail with a customer-data-bearing error ...
    end;
}
