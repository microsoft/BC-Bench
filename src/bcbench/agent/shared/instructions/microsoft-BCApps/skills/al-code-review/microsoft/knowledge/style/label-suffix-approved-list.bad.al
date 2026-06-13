codeunit 50201 "Sample Label Suffix Bad"
{
    var
        CannotDeleteLine: Label 'Cannot delete this line.';
        Text000: Label 'Update complete';
        UpdateLocation: Label 'Update location?';
        WrongSuffixTok: Label 'Customer %1 not found.';

    procedure ShowMessages()
    begin
        Error(WrongSuffixTok, '10000');
        Message(Text000);
    end;
}
