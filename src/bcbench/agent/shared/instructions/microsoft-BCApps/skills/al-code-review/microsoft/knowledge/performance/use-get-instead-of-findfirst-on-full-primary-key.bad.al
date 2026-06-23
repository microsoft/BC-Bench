codeunit 50211 "Perf Sample GetByPK Bad"
{
    procedure ShowName(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        Customer.SetRange("No.", CustomerNo);
        if Customer.FindFirst() then
            Message(Customer.Name);
    end;
}
