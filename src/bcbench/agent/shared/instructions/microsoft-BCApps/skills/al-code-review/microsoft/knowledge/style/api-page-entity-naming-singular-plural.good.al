page 50223 "Sample API Entity Good"
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

page 50224 "Sample API Compound Good"
{
    PageType = API;
    APIPublisher = 'contoso';
    APIGroup = 'app1';
    APIVersion = 'v1.0';
    EntityName = 'salesOrder';
    EntitySetName = 'salesOrders';
    SourceTable = "Sales Header";
    DelayedInsert = true;
}
