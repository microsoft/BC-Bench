codeunit 50215 "Perf Sample GuardBeforeGet Bad"
{
    procedure ResolveAllocation(var PurchaseLine: Record "Purchase Line")
    var
        PurchaseHeader: Record "Purchase Header";
    begin
        // Wasted lookup when the line has no allocation account: the procedure
        // exits below, but the header was already fetched.
        PurchaseHeader.Get(PurchaseLine."Document Type", PurchaseLine."Document No.");
        if PurchaseLine."Selected Alloc. Account No." = '' then
            exit;
        // ...
    end;
}
