codeunit 50221 "Sec Sample UrlValidation Good"
{
    procedure SyncWithExternalService(ServiceUrl: Text)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        Uri: Codeunit Uri;
    begin
        if not Uri.AreURIsHaveSameHost(ServiceUrl, 'https://api.contoso.com') then
            Error('Service URL must point to api.contoso.com');
        HttpClient.Get(ServiceUrl, Response);
    end;

    procedure SyncWithShopify(ShopUrl: Text)
    var
        HttpClient: HttpClient;
        Response: HttpResponseMessage;
        Uri: Codeunit Uri;
    begin
        if not Uri.IsValidURIPattern(ShopUrl, 'https://*.myshopify.com/*') then
            Error('Shop URL must match the Shopify pattern');
        HttpClient.Get(ShopUrl + '/admin/api/2024-01/orders.json', Response);
    end;
}
