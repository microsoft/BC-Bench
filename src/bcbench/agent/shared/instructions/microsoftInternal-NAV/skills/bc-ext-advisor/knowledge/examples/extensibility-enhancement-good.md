# Extensibility Enhancement — Good Example

A well-formed general extensibility request that adds structure or capability to enable future extensions, but does not fit the event, external-access, or enum categories.

## Why do you need this change?

`Page 8901 "Finance Manager Role Center"` has no layout section, so we cannot extend it to add Power BI parts. Extensions that pair with this RoleCenter cannot customize the UI without modifying base code.

## Describe the request

Add an empty `layout` section with `area(rolecenter)` to the RoleCenter so extensions can add parts and customize the UI.

```al
page 8901 "Finance Manager Role Center"
{
    Caption = 'Finance Manager Role Center';
    PageType = RoleCenter;

    layout
    {
        area(rolecenter)
        {
        }
    }

    actions
    {
        // ... existing actions ...
    }
}
```

Why this is good: the enhancement is precise (one missing structural element), has a concrete business need (Power BI extensibility), and enables future extensions without changing existing behavior.
