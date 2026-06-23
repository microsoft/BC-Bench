codeunit 50233 "Sample Not Spacing Bad"
{
    procedure Check(): Boolean
    var
        Customer: Record Customer;
    begin
        if NOT Customer.IsEmpty() then
            exit(true);
        exit(false);
    end;
}
