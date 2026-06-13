codeunit 50209 "Privacy Sample GetLastError Bad"
{
    procedure AddAttachment()
    var
        ErrorMsg: Text;
    begin
        if not TryAddAttachment() then begin
            ErrorMsg := StrSubstNo('Attachment failed: %1', GetLastErrorText(true));
            Error(ErrorMsg);
        end;
    end;

    [TryFunction]
    local procedure TryAddAttachment()
    begin
    end;
}
