codeunit 50214 "Perf Sample GuardBeforeGet Good"
{
    procedure ResolveAllocation(var PurchaseLine: Record "Purchase Line")
    var
        PurchaseHeader: Record "Purchase Header";
    begin
        if PurchaseLine."Selected Alloc. Account No." = '' then
            exit;
        PurchaseHeader.Get(PurchaseLine."Document Type", PurchaseLine."Document No.");
        // ...
    end;
}
