tableextension 50203 "Customer Order Stats" extends Customer
{
    fields
    {
        field(50203; "Open Order Count"; Integer)
        {
            FieldClass = FlowField;
            CalcFormula = count("Sales Header" where("Sell-to Customer No." = field("No.")));
            Caption = 'Open Order Count';
        }

        field(50204; "Date Filter"; Date)
        {
            FieldClass = FlowFilter;
            Caption = 'Date Filter';
        }
    }
}
