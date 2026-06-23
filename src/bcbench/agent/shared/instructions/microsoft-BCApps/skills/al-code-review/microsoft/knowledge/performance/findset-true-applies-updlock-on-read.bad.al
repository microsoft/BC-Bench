codeunit 50237 "Perf Sample FindSetTrue Bad"
{
    procedure NormalizeNames()
    var
        Customer: Record Customer;
    begin
        // Read takes a shared lock; the Modify then needs to upgrade — that gap
        // is the deadlock window FindSet(true) was designed to close.
        if Customer.FindSet() then
            repeat
                Customer.Name := UpperCase(Customer.Name);
                Customer.Modify();
            until Customer.Next() = 0;
    end;

    procedure ReadOnlyOverlocked()
    var
        Customer: Record Customer;
    begin
        // No Modify in the loop, yet every row is read under UpdLock.
        if Customer.FindSet(true) then
            repeat
            until Customer.Next() = 0;
    end;
}
