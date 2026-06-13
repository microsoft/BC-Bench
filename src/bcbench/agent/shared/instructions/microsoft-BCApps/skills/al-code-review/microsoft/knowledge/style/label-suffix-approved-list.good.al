codeunit 50200 "Sample Label Suffix Good"
{
    var
        UpdateCompleteMsg: Label 'Update complete.';
        CustomerNotFoundErr: Label 'Customer %1 does not exist.';
        DeleteRecordQst: Label 'Delete this record?';
        CustomerNameLbl: Label 'Customer Name';
        GetMethodTok: Label 'GET', Locked = true;
        TelemetryStartedTxt: Label 'Operation started for customer %1.', Locked = true;

    procedure ShowMessage()
    begin
        Message(UpdateCompleteMsg);
    end;
}
