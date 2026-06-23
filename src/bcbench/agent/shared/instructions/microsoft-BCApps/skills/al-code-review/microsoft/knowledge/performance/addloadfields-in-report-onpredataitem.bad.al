report 50221 "Perf Sample AddLoadFields Bad"
{
    dataset
    {
        // No AddLoadFields: every Cust. Ledger Entry column ships per row, even though
        // only three columns feed the layout.
        dataitem(CustLedgerEntry; "Cust. Ledger Entry")
        {
            column(CustomerNo; "Customer No.") { }
            column(PostingDate; "Posting Date") { }
            column(Amount; Amount) { }
        }
    }
}
