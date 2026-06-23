codeunit 50248 "Sample No Shadow Good"
{
    var
        CustomerRec: Record Customer;

    procedure ProcessSales()
    var
        CustomerName: Text;
        SalesAmount: Decimal;
    begin
        CustomerName := CustomerRec.Name;
        SalesAmount := GetAmount();
    end;

    procedure GetAmount(): Decimal
    begin
        exit(0);
    end;
}
