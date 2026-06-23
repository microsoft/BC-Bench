codeunit 50229 "Perf Sample FilterEarly Bad"
{
    procedure ProcessUSCustomers()
    var
        Customer: Record Customer;
    begin
        // Reads every customer in the table, discards the non-US ones in AL.
        if Customer.FindSet() then
            repeat
                if Customer."Country/Region Code" = 'US' then
                    ProcessCustomer(Customer);
            until Customer.Next() = 0;
    end;

    local procedure ProcessCustomer(var Customer: Record Customer)
    begin
    end;
}
