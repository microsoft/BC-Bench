codeunit 50242 "Perf Sample ModifyAll Good"
{
    procedure ApplyPriceUpdate(NewPrice: Decimal)
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetRange(Type, SalesLine.Type::Item);
        SalesLine.ModifyAll("Unit Price", NewPrice);
    end;

    procedure ApplyTolerance(DocumentNo: Code[20]; ToleranceAmount: Decimal)
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
    begin
        CustLedgerEntry.SetRange("Document No.", DocumentNo);
        CustLedgerEntry.SetRange(Open, true);
        CustLedgerEntry.ModifyAll("Accepted Payment Tolerance", ToleranceAmount);
        CustLedgerEntry.ModifyAll("Accepted Pmt. Disc. Tolerance", false);
    end;
}
