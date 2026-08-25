# IsHandled Event Request — Good Example

A well-formed request for a new event exposing an `IsHandled` bypass. Only use this shape when the request explicitly asks to skip existing logic.

## Why do you need this change?

Our localization must replace the standard document number assignment in `Codeunit 80 "Sales-Post"` with a country-specific number series that depends on the customer's tax registration. The standard assignment logic cannot be reused, and there is no existing event that lets us substitute it. Alternatives evaluated: `OnBeforePostSalesDoc` (fires too early) and `OnAfterPostSalesDoc` (fires too late — the number is already assigned).

## Describe the request

Add a new `IntegrationEvent` with an `IsHandled` parameter immediately before the standard number-assignment block, so subscribers can supply the number themselves.

```al
var
    IsHandled: Boolean;
begin
    IsHandled := false;
    OnBeforeAssignDocumentNo(SalesHeader, IsHandled);
    if not IsHandled then
        AssignDocumentNo(SalesHeader);
end;

[IntegrationEvent(false, false)]
local procedure OnBeforeAssignDocumentNo(var SalesHeader: Record "Sales Header"; var IsHandled: Boolean)
begin
end;
```

Performance: runs once per posted document, negligible impact. Data sensitivity: no sensitive data involved. Multi-extension interaction: only our localization subscribes; conflicts are not expected. Note the mandatory `IsHandled := false;` initialization immediately before the call.
