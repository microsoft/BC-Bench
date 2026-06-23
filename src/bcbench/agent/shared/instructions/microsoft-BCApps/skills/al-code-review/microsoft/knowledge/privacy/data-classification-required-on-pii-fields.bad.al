tableextension 50201 "Customer Contact Ext Bad" extends Customer
{
    fields
    {
        field(50201; "Secondary Email"; Text[80])
        {
            DataClassification = SystemMetadata;
            Caption = 'Secondary Email';
        }
    }
}
