codeunit 50209 "Perf Sample FindSetNext Bad"
{
    procedure SumCustomerBalances() Total: Decimal
    var
        Customer: Record Customer;
    begin
        // AA0233: FindFirst paired with Next — single-row API used to iterate.
        if Customer.FindFirst() then
            repeat
                Total += Customer."Balance (LCY)";
            until Customer.Next() = 0;
    end;
}
