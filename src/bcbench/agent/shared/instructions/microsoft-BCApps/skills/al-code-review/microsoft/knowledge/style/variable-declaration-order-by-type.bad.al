codeunit 50247 "Sample Var Order Bad"
{
    procedure Run()
    var
        CustomerNo: Code[20];
        TempBuffer: Record "Integer" temporary;
        Amount: Decimal;
        Customer: Record Customer;
        IsValid: Boolean;
    begin
        IsValid := Customer.Get(CustomerNo);
    end;
}
