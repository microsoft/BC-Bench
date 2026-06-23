table 50227 "Perf Sample FA Journal Tmpl"
{
    fields
    {
        field(1; Name; Code[10]) { }
        field(40; "No. of Lines"; Integer)
        {
            FieldClass = FlowField;
            // Source key below has MaintainSQLIndex = false: SIFT cannot
            // function, so this COUNT runs without a SQL index.
            CalcFormula = count("FA Journal Line"
                                where("Journal Template Name" = field(Name)));
        }
    }
}

tableextension 50228 "Perf Sample FA Jnl Line Ext" extends "FA Journal Line"
{
    keys
    {
        key(PerfSampleByTemplate; "Journal Template Name", "Journal Batch Name")
        {
            MaintainSQLIndex = false;
        }
    }
}
