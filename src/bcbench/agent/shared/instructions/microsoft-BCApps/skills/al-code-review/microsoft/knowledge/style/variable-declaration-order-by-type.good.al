codeunit 50246 "Sample Var Order Good"
{
    procedure Run()
    var
        Customer: Record Customer;
        TempBuffer: Record "Integer" temporary;
        CustomerNo: Code[20];
        Amount: Decimal;
        IsValid: Boolean;
    begin
        IsValid := Customer.Get(CustomerNo);
    end;
}
