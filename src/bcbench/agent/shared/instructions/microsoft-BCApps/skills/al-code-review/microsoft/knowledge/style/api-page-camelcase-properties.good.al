page 50218 "Sample API Camel Good"
{
    PageType = API;
    APIPublisher = 'contoso';
    APIGroup = 'app1';
    APIVersion = 'v2.0';
    EntityName = 'customer';
    EntitySetName = 'customers';
    SourceTable = Customer;
    DelayedInsert = true;

    layout
    {
        area(Content)
        {
            repeater(Group)
            {
                field(displayName; Rec.Name) { Caption = 'displayName'; }
            }
        }
    }
}
