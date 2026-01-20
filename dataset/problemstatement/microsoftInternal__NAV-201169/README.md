# Title: Shopify. Export item with empty title should be logged in Skipped entries
## Repro Steps:
Create item with no description.
Try to Add this item to Shopify.

I can see two entries:
1.  failed:
Request:
{"query":"mutation {productCreate(input: {**title:****"****",** status: ACTIVE, published: true}) {product {legacyResourceId, onlineStoreUrl, onlineStorePreviewUrl, createdAt, updatedAt, tags, variants(first: 1) {edges {node {legacyResourceId, createdAt, updatedAt}}}}, userErrors {field, message}}}"}
Response:
{"data":{"productCreate":{"product":null,"userErrors":[{"field":["title"],"**message":"Title can't be blank"**}]}},"extensions":{"cost":{"requestedQueryCost":13,"actualQueryCost":10,"throttleStatus":{"maximumAvailable":4000.0,"currentlyAvailable":3990,"restoreRate":200.0}}}}
Expected - we should not try to export this item. But add it to Skipped entries.

2. 
Also I notice that there was another pair (maybe fixed in main)
{"query":"{ translatableResource(resourceId: "gid://shopify/Product/0") { resourceId translatableContent {key value digest locale} }}"}
with request for translatable resources for item that wasn't created. I suspect we fixed something similar for metafields. But apparently it is still there for items (if for any other reason Shopify will reject creation of item)

## Description:
