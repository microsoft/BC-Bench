codeunit 50212 "Sample Parens Good"
{
    procedure Run()
    var
        Customer: Record Customer;
    begin
        Customer.Init();
        if Customer.FindFirst() then
            Customer.Modify();
    end;
}
