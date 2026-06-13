codeunit 50223 "Perf Sample CalcSums Bad"
{
    procedure TotalRemaining(CustomerNo: Code[20]) Total: Decimal
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
    begin
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        // One SQL query per row over a 10M-row ledger.
        if CustLedgerEntry.FindSet() then
            repeat
                CustLedgerEntry.CalcFields("Remaining Amount");
                Total += CustLedgerEntry."Remaining Amount";
            until CustLedgerEntry.Next() = 0;
    end;
}
