# [Shopify] Auto Create Catalog: always visible, validate plan on enable

## Summary

Re-fix for **bug 630316** after PM verification of [PR #7605](https://github.com/microsoft/BCApps/pull/7605).

PR #7605 made B2B features unconditional on all Shopify plans, but the `Auto Create Catalog` toggle on the **Customers and Companies** group of the Shop Card stayed hidden for non-Advanced shops because its `Visible = Rec."Advanced Shopify Plan"` binding is not re-evaluated after `GetShopSettings()` flips the flag at runtime.

Per PM Andrei Pankos guidance:
- Drop the dynamic visibility on the `Auto Create Catalog` field so its always visible in the Companies group.
- Gate the field at the table layer instead: an `OnValidate` trigger raises a field error if the user tries to enable `Auto Create Catalog` on a shop whose plan does not support B2B catalogs (Plus, Plus Trial, Development, or Advanced).

The error uses the existing `ErrorInfo` / `FieldNo` pattern already used elsewhere in `ShpfyShop.Table.al` (e.g. field 21 `Auto Create Orders`).

## What is NOT changed

- `action(Catalogs)` (B2B Catalogs action) and `action(StaffMembers)` visibility on the Shop Card  PM only flagged the field control.
- The runtime `Shop."Auto Create Catalog"` checks in `ShpfyCompanyAPI.Codeunit.al` / `ShpfyCompanyExport.Codeunit.al`  the table guard prevents the boolean from being set to `true` on an unsupported plan, so no runtime check is needed.
- The `B2B Enabled` obsoletion and upgrade code from PR #7605  already accepted by PM.
- `app.json` versions  intentionally untouched.

## Test

Adds `TestAutoCreateCatalogRequiresAdvancedPlan` to `ShpfyStaffTest` (codeunit 139551, which is already the home for `Advanced Shopify Plan`-gated tests). Verified both passes locally:

```
PASS TestStaffMembersActionVisibleOnlyForSupportedPlans (513ms)
PASS TestAutoCreateCatalogRequiresAdvancedPlan (23ms)
```

Fixes [AB#630316](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/630316)



