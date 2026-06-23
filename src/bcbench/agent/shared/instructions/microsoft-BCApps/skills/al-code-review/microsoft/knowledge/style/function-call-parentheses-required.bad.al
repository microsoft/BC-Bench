codeunit 50213 "Sample Parens Bad"
{
    procedure Run()
    var
        Customer: Record Customer;
    begin
        Customer.Init;
        if Customer.FindFirst then
            Customer.Modify;
    end;
}
