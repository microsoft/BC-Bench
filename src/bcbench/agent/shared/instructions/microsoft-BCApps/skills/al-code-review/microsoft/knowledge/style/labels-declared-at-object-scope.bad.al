codeunit 50262 "Sample Label Scope Bad"
{
    procedure LookupCustomer(CustomerNo: Code[20])
    var
        Customer: Record Customer;
        GreetingMsg: Label 'Hello %1', Comment = '%1 = Customer Name';
    begin
        if Customer.Get(CustomerNo) then
            Message(GreetingMsg, Customer.Name);
    end;
}
