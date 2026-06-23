table 50252 "Sample Caption Good"
{
    fields
    {
        field(1; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
        }
        field(2; "Enabled"; Boolean)
        {
        }
        field(3; Amount; Decimal)
        {
            CaptionClass = '3,5,' + 'USD';
        }
    }
}
