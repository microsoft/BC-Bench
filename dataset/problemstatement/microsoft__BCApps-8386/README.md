# [Shopify] Tolerate legacy bulk-operation request data missing unitCost key

## Summary
Bulk variant price updates persist a JSON `Request Data` blob on `Shpfy Bulk Operation` so the rollback path can restore the previous Price / Compare-at-Price / Updated At / Unit Cost values when Shopify's async callback reports failure.

PR #6155 added a new `unitCost` key to that blob and a matching reader on the rollback path, but the reader uses `JsonObject.GetDecimal` which throws if the key is missing. Any bulk operation queued **before** the upgrade (no `unitCost` in the blob) and reverted **after** the upgrade crashes with:

> There are no properties with the key 'unitCost' on the JSON object

The same stale rows can keep retrying, so the error surfaces repeatedly even though the upgrade happened once.

The Shopify API payload itself is unaffected — it still correctly sends `inventoryItem.cost`. The crash is purely on the BC-side rollback reader.

## Changes

**Production code**
- `ShpfyBulkUpdateProductPrice.RevertRequests` and `ShpfyProductExport.RevertVariantChanges`: guard the `unitCost` read with `JsonObject.Contains('unitCost')`. If absent (legacy blob), Unit Cost is left untouched, matching the pre-PR-#6155 behaviour.

**Test code**
- `TestBulkOperationRevertFailedWithLegacyRequestDataMissingUnitCost`: new regression test that builds a request-data blob without the `unitCost` key (via a `GenerateLegacyRequestDataWithoutUnitCost` helper) and asserts that the rollback completes without throwing, reverts Price / Compare-at-Price correctly, and leaves Unit Cost untouched.

## Why only `unitCost` is gated, not every field
The other keys (`id`, `price`, `compareAtPrice`, `updatedAt`) have been written by `ShpfyVariantAPI.UpdateProductPrice` since the connector was first migrated to BCApps — there is no version that ever persisted a `Request Data` blob without them. A missing `price`/`compareAtPrice`/`updatedAt`/`id` is therefore not a legitimate "legacy blob" scenario; it would be a real upstream bug (regressed writer, corrupted blob, forgotten `JRequest.Add`). `GetDecimal`'s throw is the correct behaviour there — surfacing the bug loudly is better than silently skipping a rollback (which would leave variants showing the wrong price in BC, or no-op the revert with zero diagnostic).

`unitCost` is the one and only key that was added later, so it's the one key where a key-missing scenario has both a legitimate root cause (legacy persisted blob) and a safe fallback (leave the field untouched).

## Customer mitigation (no patch required)
Customers hitting this on the current BC28 build can self-mitigate by opening the **Shopify Bulk Operations** page and running **Delete Entries Older Than 7 Days**. The deletion bypasses the rollback trigger, removing the stale pre-upgrade rows without re-throwing. Bulk operations queued after the upgrade are written in the new layout and are unaffected.

## Scope
Main only — rare upgrade-window race condition with a self-service mitigation available. Not backported.

#### Work Item(s)
Fixes [AB#637250](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/637250)
