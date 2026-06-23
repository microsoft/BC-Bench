codeunit 50228 "Perf Sample FilterEarly Good"
{
    procedure ProcessUSCustomers()
    var
        Customer: Record Customer;
    begin
        Customer.SetRange("Country/Region Code", 'US');
        if Customer.FindSet() then
            repeat
                ProcessCustomer(Customer);
            until Customer.Next() = 0;
    end;

    local procedure ProcessCustomer(var Customer: Record Customer)
    begin
    end;
}
