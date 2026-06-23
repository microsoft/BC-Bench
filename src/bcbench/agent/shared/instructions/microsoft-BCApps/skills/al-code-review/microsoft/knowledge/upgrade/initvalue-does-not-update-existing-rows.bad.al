tableextension 50224 "MyTable Ext" extends "My Table"
{
    fields
    {
        // InitValue only applies to rows inserted after deployment.
        // Pre-existing rows silently carry the datatype default (false).
        field(50200; "New Flag"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'New Flag';
            InitValue = true;
        }
    }
    // No accompanying upgrade codeunit to back-fill existing rows.
}
