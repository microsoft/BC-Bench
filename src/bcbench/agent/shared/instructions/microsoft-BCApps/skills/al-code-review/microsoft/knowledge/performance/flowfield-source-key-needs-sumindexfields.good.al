tableextension 50224 "Perf Sample SIFT Good Ext" extends "Detailed Cust. Ledg. Entry"
{
    keys
    {
        key(PerfSampleByCustomer; "Customer No.", "Posting Date")
        {
            SumIndexFields = "Debit Amount";
        }
    }
}

tableextension 50225 "Perf Sample SIFT Good Cust" extends Customer
{
    fields
    {
        field(50225; "Perf Sample Total Debit"; Decimal)
        {
            FieldClass = FlowField;
            CalcFormula = sum("Detailed Cust. Ledg. Entry"."Debit Amount"
                              where("Customer No." = field("No.")));
        }
    }
}
