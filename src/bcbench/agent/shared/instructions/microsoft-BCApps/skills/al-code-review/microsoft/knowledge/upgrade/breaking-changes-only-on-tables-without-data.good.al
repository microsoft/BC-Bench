// New feature table introduced in the same change as the keys / field types.
// No existing data, so the layout is free to choose.
table 50232 "New Feature Table"
{
    fields
    {
        field(1; "Entry No."; BigInteger) { }
        field(2; "Customer No."; Code[20]) { }
        field(3; "Posting Date"; Date) { }
    }
    keys
    {
        key(PK; "Entry No.") { Clustered = true; }
        key(ByCustomer; "Customer No.", "Posting Date") { }
    }
}
