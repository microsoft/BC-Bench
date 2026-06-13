codeunit 50214 "Sample This Good"
{
    procedure ProcessRecord(Customer: Record Customer)
    var
        Helper: Codeunit "Sample This Helper";
    begin
        this.ValidateCustomer(Customer);
        Helper.DoWork(this);
    end;

    local procedure ValidateCustomer(Customer: Record Customer)
    begin
    end;
}
