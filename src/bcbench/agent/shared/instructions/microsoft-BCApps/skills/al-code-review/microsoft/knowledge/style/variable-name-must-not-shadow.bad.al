codeunit 50249 "Sample Shadow Bad"
{
    var
        Customer: Record Customer;

    procedure ProcessSales()
    var
        Customer: Text;
        Amount: Decimal;
    begin
        Customer := 'C-100';
        Amount := 0;
    end;

    procedure Amount(): Decimal
    begin
        exit(0);
    end;
}
