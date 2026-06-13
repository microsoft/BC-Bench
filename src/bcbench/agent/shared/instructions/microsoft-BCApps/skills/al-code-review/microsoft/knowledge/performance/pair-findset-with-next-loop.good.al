codeunit 50208 "Perf Sample FindSetNext Good"
{
    procedure SumCustomerBalances() Total: Decimal
    var
        Customer: Record Customer;
    begin
        if Customer.FindSet() then
            repeat
                Total += Customer."Balance (LCY)";
            until Customer.Next() = 0;
    end;

    procedure GetFirstUSCustomer(var Customer: Record Customer): Boolean
    begin
        Customer.SetRange("Country/Region Code", 'US');
        exit(Customer.FindFirst());
    end;
}
