page 50220 "Sample API Version Good"
{
    PageType = API;
    APIPublisher = 'contoso';
    APIGroup = 'app1';
    APIVersion = 'v1.0';
    EntityName = 'customer';
    EntitySetName = 'customers';
    SourceTable = Customer;
    DelayedInsert = true;
}

page 50221 "Sample API Beta Good"
{
    PageType = API;
    APIPublisher = 'contoso';
    APIGroup = 'app1';
    APIVersion = 'beta';
    EntityName = 'preview';
    EntitySetName = 'previews';
    SourceTable = Customer;
    DelayedInsert = true;
}
