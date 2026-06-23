tableextension 50210 "Sample FieldCaption Good" extends Customer
{
    procedure ConfirmAndAnnounce(): Boolean
    var
        UpdateLocationQst: Label 'Update %1?';
        UpdatedMsg: Label 'Updated %1.';
    begin
        if not Confirm(UpdateLocationQst, true, FieldCaption("Location Code")) then
            exit(false);
        Message(UpdatedMsg, TableCaption());
        exit(true);
    end;
}
