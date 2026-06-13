tableextension 50200 "Customer Contact Ext" extends Customer
{
    fields
    {
        field(50200; "Secondary Email"; Text[80])
        {
            DataClassification = CustomerContent;
            Caption = 'Secondary Email';
        }
    }
}
