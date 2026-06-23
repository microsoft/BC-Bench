tableextension 50211 "Sample FieldCaption Bad" extends Customer
{
    procedure ConfirmAndAnnounce(): Boolean
    var
        UpdateLocationQst: Label 'Update %1?';
        UpdatedMsg: Label 'Updated %1.';
    begin
        if not Confirm(UpdateLocationQst, true, FieldName("Location Code")) then
            exit(false);
        Message(UpdatedMsg, TableName());
        exit(true);
    end;
}
