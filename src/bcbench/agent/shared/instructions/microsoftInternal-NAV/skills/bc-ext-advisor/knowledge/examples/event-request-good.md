# Event Request — Good Example

A well-formed request to add a new publisher event.

## Why do you need this change?

Our extension needs to run custom validation after a sales line quantity is validated, but before the document is posted. There is currently no event at this point in `Codeunit 80 "Sales-Post"`, so we cannot hook in without modifying base code.

## Describe the request

Add a new `IntegrationEvent` immediately after the quantity validation block in `Codeunit 80 "Sales-Post"`, passing the sales header and sales line by value.

```al
[IntegrationEvent(false, false)]
local procedure OnAfterValidateSalesLineQuantity(SalesHeader: Record "Sales Header"; SalesLine: Record "Sales Line")
begin
end;
```

Why this is good: the target is a Microsoft base-app object, the location and signature are exact, the business need is concrete, and the code is provided as a fenced AL block.
