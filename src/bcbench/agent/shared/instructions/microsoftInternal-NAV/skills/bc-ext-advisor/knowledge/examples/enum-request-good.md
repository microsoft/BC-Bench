# Enum Request — Good Example

A well-formed request to extend an existing extensible enum.

## Why do you need this change?

Our extension adds a new shipping integration. The standard `Enum 7000 "Sales Line Type"` does not include a value for our integration's line handling, and we need the base posting routine to recognize it. The enum is marked `Extensible = true`, so an `enumextension` is possible.

## Describe the request

Add a new value to `Enum 7000 "Sales Line Type"` via extension.

```al
enumextension 50100 "Sales Line Type Ext" extends "Sales Line Type"
{
    value(50100; "Freight Service")
    {
        Caption = 'Freight Service';
    }
}
```

Compatibility: the base `case` statements on this enum include an `else` branch, so unknown values are handled gracefully. The chosen ordinal (50100) is inside our registered extension range and does not conflict with other extensions. No data migration is required.
