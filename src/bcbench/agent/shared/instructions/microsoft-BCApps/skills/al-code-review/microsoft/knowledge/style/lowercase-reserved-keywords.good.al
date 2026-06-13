codeunit 50244 "Sample Lower Keywords Good"
{
    procedure Walk(var Customer: Record Customer)
    var
        Found: Boolean;
    begin
        if Customer.FindSet() then
            repeat
                Found := true;
            until Customer.Next() = 0;
        if Found then
            exit;
    end;
}
