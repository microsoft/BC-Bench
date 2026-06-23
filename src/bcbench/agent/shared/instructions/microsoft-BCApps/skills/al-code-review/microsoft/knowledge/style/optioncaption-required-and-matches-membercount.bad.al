table 50255 "Sample OptionCaption Bad"
{
    fields
    {
        field(1; Status; Option)
        {
            Caption = 'Status';
            OptionMembers = Open,Released,Pending;
        }
        field(2; Priority; Option)
        {
            Caption = 'Priority';
            OptionMembers = Low,Medium,High,Critical;
            OptionCaption = 'Low,Medium,High';
        }
    }
}
