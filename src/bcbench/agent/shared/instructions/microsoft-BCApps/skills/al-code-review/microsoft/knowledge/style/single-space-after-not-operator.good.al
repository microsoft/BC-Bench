codeunit 50232 "Sample Not Spacing Good"
{
    procedure Check(): Boolean
    var
        Customer: Record Customer;
    begin
        if not Customer.IsEmpty() then
            exit(true);
        exit(false);
    end;
}
