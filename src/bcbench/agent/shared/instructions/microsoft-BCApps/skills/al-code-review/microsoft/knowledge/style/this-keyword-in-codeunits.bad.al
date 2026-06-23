codeunit 50215 "Sample This Bad"
{
    procedure ProcessRecord(Customer: Record Customer)
    var
        Helper: Codeunit "Sample This Helper";
    begin
        ValidateCustomer(Customer);
        Helper.DoWork();
    end;

    local procedure ValidateCustomer(Customer: Record Customer)
    begin
    end;
}
