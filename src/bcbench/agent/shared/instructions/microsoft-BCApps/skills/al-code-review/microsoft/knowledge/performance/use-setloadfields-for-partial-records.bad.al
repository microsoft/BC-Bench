codeunit 50219 "Perf Sample LoadFields Bad"
{
    procedure ListUSCustomerNames()
    var
        Customer: Record Customer;
    begin
        // Loads every Customer column on every row, when only Name is read.
        Customer.SetRange("Country/Region Code", 'US');
        if Customer.FindSet() then
            repeat
                Message(Customer.Name);
            until Customer.Next() = 0;
    end;
}
