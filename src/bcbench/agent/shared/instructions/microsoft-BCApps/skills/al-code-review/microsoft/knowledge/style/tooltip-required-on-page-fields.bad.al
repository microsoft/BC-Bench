page 50251 "Sample Tooltip Bad"
{
    PageType = Card;
    SourceTable = Customer;
    layout
    {
        area(Content)
        {
            group(General)
            {
                field("No."; Rec."No.")
                {
                    ApplicationArea = All;
                }
                field(Amount; Rec."Balance (LCY)")
                {
                    ApplicationArea = All;
                    ToolTip = '';
                }
            }
        }
    }
}
