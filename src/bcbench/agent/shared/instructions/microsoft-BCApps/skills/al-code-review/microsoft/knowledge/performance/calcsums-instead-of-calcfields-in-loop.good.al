codeunit 50222 "Perf Sample CalcSums Good"
{
    procedure TotalRemaining(CustomerNo: Code[20]) Total: Decimal
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
    begin
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        CustLedgerEntry.CalcSums("Remaining Amount");
        Total := CustLedgerEntry."Remaining Amount";
    end;
}
