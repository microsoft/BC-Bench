# Bug 638458: Disable subcontracting actions on Item Ledger Entries when not applicable

## Summary
- **Bug:** Item Ledger Entries subcontracting actions (Production Order, Production Order Routing, Production Order Components, Subcontracting Purchase Order) are always enabled and silently do nothing when clicked on non-subcontracting entries.
- **Root cause:** The four actions in `SubcILEntries.PageExt.al` had no `Enabled` property, so they were always clickable regardless of whether the entry was subcontracting-related.
- **Fix:** Added inline `Enabled` expressions:
  - `Enabled = Rec."Subc. Prod. Order No." <> ''` on Production Order, Production Order Routing, and Production Order Components actions
  - `Enabled = Rec."Subc. Purch. Order No." <> ''` on Subcontracting Purchase Order action

## Test
Added `ItemLedgerEntriesSubcActionsDisabledWhenNotSubcontracting` and `ItemLedgerEntriesSubcActionsEnabledWhenSubcontracting` in `SubcSubcontractingUITest` (codeunit 139990) — [SCENARIO 638458].

Fixes [AB#638458](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/638458)

:robot: Generated with GitHub Copilot
