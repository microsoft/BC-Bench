tableextension 50226 "Perf Sample SIFT Bad Cust" extends Customer
{
    fields
    {
        // No SIFT key on Detailed Cust. Ledg. Entry for (Customer No.) with
        // "Debit Amount" in SumIndexFields — the sum falls back to row-by-row
        // aggregation over a ledger-scale table.
        field(50226; "Perf Sample Total Debit"; Decimal)
        {
            FieldClass = FlowField;
            CalcFormula = sum("Detailed Cust. Ledg. Entry"."Debit Amount"
                              where("Customer No." = field("No.")));
        }
    }
}
