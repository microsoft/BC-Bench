# [Shopify] Refresh cached plan before order sync

## Summary

Bug 635878: When a merchant downgrades their Shopify plan from Plus / Advanced to a standard plan, the connector keeps requesting the `staffMember { id }` field in the order GraphQL query. The lower plan does not grant `read_users` scope, so Shopify returns `ACCESS_DENIED` and order sync is fully broken until the user manually toggles the **Enabled** field off and on again on the Shop Card.

`Shop."Advanced Shopify Plan"` (field 207) is the cached flag that gates the staff member field. It was only refreshed when the user toggled Enabled or when a scope change was detected on Shop Card open — never before an order sync.

## Fix

Auto-refresh the cached plan via the existing `Shop.GetShopSettings()` helper (one cheap GraphQL query for `shop { plan { ... } weightUnit }`) before both order-import entry points:

1. **Bulk sync** — Report `30104 Shpfy Sync Orders from Shopify` (also the scheduled auto-sync path). One refresh call per shop per batch run.
2. **Single-order reimport** — `ShpfyImportOrder.ReimportExistingOrderConfirmIfConflicting` (manual reimport action on the Order Header page).

The refresh is deliberately not placed in `ShpfyImportOrder.SetShop()` because that runs per order; for a 100-order batch it would mean 100 extra GraphQL round-trips.

## Tests

Two regression tests added to the existing `ShpfyOrdersAPITest.Codeunit.al` (139608):

- `TestGetShopSettingsClearsStaleAdvancedShopifyPlanFlag` — sets stale `"Advanced Shopify Plan" = true`, calls `GetShopSettings`, asserts the flag becomes `false`.
- `TestSyncOrdersFromShopifyReportRefreshesAdvancedShopifyPlanFlag` — sets stale flag, runs Report 30104, asserts the persisted Shop record has the flag refreshed to `false`.

Existing `OrdersAPIHttpHandler` extended with a one-shot `PlanRefreshExpected` flag returning a downgraded-plan JSON for the first request, then falling through to the prior empty-data behavior.

Both tests verified locally.

Fixes [AB#635878](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/635878)






