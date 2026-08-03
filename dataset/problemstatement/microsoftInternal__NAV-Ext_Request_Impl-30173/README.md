# Extensibility request: two integration events on page 7004 "Sales Line Discounts"

## Why do you need this change?

These event requests are related to an earlier case. In every request we will need the variable
`ItemTypeFilter` (currently an option, which we separately requested to change to an enum).

### 1. Procedure SetRecFilters

We need a new integration event in procedure `SetRecFilters`. We have extended page "Sales Line Discounts"
with additional fields backed by global variables. To properly control filtering and behavior, we need
access to the page instance (`var SalesLineDiscounts`) within the event, so we can implement
setter/getter procedures to read/write these global values during filter setup.

Existing events (e.g. `OnOpenPage` / `OnAfterGetRecord`) do not provide sufficient control during filter
application, and table triggers are not suitable since the required logic depends on page-level global
variables and UI state.

### 2. Procedure GetFilterDescription

Introduce a new integration event in procedure `GetFilterDescription()` to extend the `case ItemTypeFilter`
logic — specifically to handle additional/custom types (equivalent to an `else` branch). The current
implementation supports only predefined `ItemTypeFilter` values (Item, Item Discount Group) and offers no
extensibility point for additional/custom types. The event should allow overriding `SourceTableName`,
applying custom filtering logic on `Item`, and extending behavior without modifying base code.

## Describe the request

### 1. Procedure SetRecFilters

```al
procedure SetRecFilters()
begin
    ...
    OnSetRecFilters(ItemTypeFilter, Rec, SalesLineDiscounts);
    CurrPage.Update(false);
end;

[IntegrationEvent(true, false)]
local procedure OnSetRecFilters(ItemTypeFilter: Enum "Item Type Filter"; var SalesLineDiscount: Record "Sales Line Discount"; var SalesLineDiscounts: Page "Sales Line Discounts")
begin
end;
```

### 2. Procedure GetFilterDescription

```al
case ItemTypeFilter of
    ItemTypeFilter::Item:
        ...
    ItemTypeFilter::"Item Discount Group":
        ...
    else
        OnItemTypeFilterElse(ItemTypeFilter, SourceTableName, Item);
end;

[IntegrationEvent(true, false)]
local procedure OnItemTypeFilterElse(ItemTypeFilter: Enum "Item Type Filter"; var SourceTableName: Text; var Item: Record Item)
begin
end;
```

## Scope

- File: `SalesLineDiscounts.Page.al`
- This page exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
