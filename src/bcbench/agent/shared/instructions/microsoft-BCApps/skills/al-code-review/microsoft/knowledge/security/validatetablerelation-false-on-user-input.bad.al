tableextension 50225 "Sec Sample VTR Bad" extends Customer
{
    fields
    {
        field(50225; "Linked Customer No."; Code[20])
        {
            TableRelation = Customer."No.";
            ValidateTableRelation = false;
        }
    }
}
