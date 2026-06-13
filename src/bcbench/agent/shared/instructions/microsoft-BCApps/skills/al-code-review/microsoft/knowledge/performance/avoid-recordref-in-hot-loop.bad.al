codeunit 50255 "Perf Sample RecRef Bad"
{
    procedure ProcessAllCustomerNames()
    var
        Customer: Record Customer;
        RecRef: RecordRef;
        FldRef: FieldRef;
    begin
        RecRef.Open(Database::Customer);
        if RecRef.FindSet() then
            repeat
                // Table and field are fixed at compile time, but every iteration
                // pays dynamic resolution cost.
                FldRef := RecRef.Field(Customer.FieldNo(Name));
                ProcessName(Format(FldRef.Value));
            until RecRef.Next() = 0;
    end;

    local procedure ProcessName(Name: Text)
    begin
    end;
}
