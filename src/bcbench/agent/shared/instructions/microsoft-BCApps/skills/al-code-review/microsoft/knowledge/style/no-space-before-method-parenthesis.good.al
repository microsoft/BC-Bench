codeunit 50230 "Sample No Space Paren Good"
{
    procedure Lookup(CustomerNo: Code[20])
    var
        Customer: Record Customer;
        GreetingMsg: Label 'Hello %1';
    begin
        if Customer.Get(CustomerNo) then
            Message(GreetingMsg, Customer.Name);
    end;
}
