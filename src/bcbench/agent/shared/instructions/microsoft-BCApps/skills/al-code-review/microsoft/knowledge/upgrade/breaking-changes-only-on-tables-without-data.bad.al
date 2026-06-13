// A pre-existing table with millions of rows. Changing the primary key or
// widening a field type without an upgrade plan can fail at deployment.
tableextension 50233 "Cust Ledger Entry Ext" extends "Cust. Ledger Entry"
{
    fields
    {
        // Widening Integer to BigInteger on an existing column with persisted data
        // requires an upgrade plan and value-range evidence; not safe as a bare edit.
        modify("Entry No.")
        {
            // (hypothetical: field type change goes here)
        }
    }
    // No accompanying upgrade codeunit, no upgrade tag, no overflow verification.
}
