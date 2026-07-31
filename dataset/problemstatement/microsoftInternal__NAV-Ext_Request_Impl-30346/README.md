# Extensibility request: make "Item Jnl.-Post Line".InsertPostValueEntryToGL externally callable

## Why this change is needed

Codeunit 22 "Item Jnl.-Post Line" exposes `PostInventoryToGL` as a public procedure, and extensions
already build on it to post additional value entries to the general ledger. The related helper
`InsertPostValueEntryToGL(ValueEntry: Record "Value Entry")` posts a single value entry to the G/L,
but it is declared `local`, so it cannot be called from an extension.

An extension that posts additional variance (or other custom value entries) needs to reuse this exact
standard logic instead of duplicating it. There is currently no supported way to do that.

## Requested change

Widen the accessibility of the `InsertPostValueEntryToGL` method in codeunit 22 "Item Jnl.-Post Line"
so it can be called from outside the codeunit: change it from a `local procedure` to a (public)
`procedure`. The body and signature stay exactly the same.

```al
// before
local procedure InsertPostValueEntryToGL(ValueEntry: Record "Value Entry")

// after
procedure InsertPostValueEntryToGL(ValueEntry: Record "Value Entry")
```

## Scope

- This codeunit is kept as a separate copy in several country/region layers. The accessibility change
  must be applied consistently to **every** layer that has a copy, so the method is public everywhere:
  - `App/Layers/W1/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
  - `App/Layers/APAC/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
  - `App/Layers/CH/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
  - `App/Layers/ES/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
  - `App/Layers/IT/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
  - `App/Layers/RU/BaseApp/Inventory/Posting/ItemJnlPostLine.Codeunit.al`
- No other layers keep a copy of this codeunit, so only these six files change.
