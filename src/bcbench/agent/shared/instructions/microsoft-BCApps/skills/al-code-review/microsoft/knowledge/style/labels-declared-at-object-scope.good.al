codeunit 50263 "Sample Label Scope Good"
{
    var
        GreetingMsg: Label 'Hello %1', Comment = '%1 = Customer Name';

    procedure LookupCustomer(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        if Customer.Get(CustomerNo) then
            Message(GreetingMsg, Customer.Name);
    end;
}
