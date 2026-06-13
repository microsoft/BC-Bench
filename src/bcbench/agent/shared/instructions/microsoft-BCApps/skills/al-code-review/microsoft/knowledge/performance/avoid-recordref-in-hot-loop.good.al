codeunit 50254 "Perf Sample RecRef Good"
{
    procedure ProcessAllCustomerNames()
    var
        Customer: Record Customer;
    begin
        if Customer.FindSet() then
            repeat
                ProcessName(Customer.Name);
            until Customer.Next() = 0;
    end;

    local procedure ProcessName(Name: Text[100])
    begin
    end;
}
