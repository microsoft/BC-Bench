codeunit 50234 "Sec Sample LastErrText"
{
    procedure RunWithCapture(var ErrorLog: Record "Integration Log")
    begin
        if not Codeunit.Run(Codeunit::"My Worker") then begin
            ErrorLog."Error Text" := CopyStr(GetLastErrorText(), 1, MaxStrLen(ErrorLog."Error Text"));
            ErrorLog.Insert(true);
        end;
    end;
}
