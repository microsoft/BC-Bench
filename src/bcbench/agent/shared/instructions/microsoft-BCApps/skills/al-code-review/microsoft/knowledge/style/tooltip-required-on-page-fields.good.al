page 50250 "Sample Tooltip Good"
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
                    ToolTip = 'Specifies the number that identifies the customer.';
                }
                field(Amount; Rec."Balance (LCY)")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the total balance in local currency.';
                }
            }
        }
    }
}
