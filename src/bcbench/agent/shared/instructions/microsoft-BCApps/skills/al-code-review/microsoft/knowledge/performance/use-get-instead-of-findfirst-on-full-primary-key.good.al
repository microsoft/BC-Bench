codeunit 50210 "Perf Sample GetByPK Good"
{
    procedure ShowName(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        if Customer.Get(CustomerNo) then
            Message(Customer.Name);
    end;
}
