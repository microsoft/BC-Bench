codeunit 50211 "Privacy Sample LogMessage Bad"
{
    procedure LogCompleted()
    begin
        Session.LogMessage('0003', 'Operation completed', Verbosity::Normal);
    end;
}
