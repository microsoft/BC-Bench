# [Shopify] Fix bulk variant price update sending compareAtPrice as "0"

## Summary
The bulk variant price update path (`productVariantsBulkUpdate` via Shopify's bulk operations API, used when RecordCount >= 100 in a single price sync) was emitting `"compareAtPrice": "0"` instead of `null` or omitting the field. Shopify stores `"0"` as a real `.00` compare-at price, which on themes that surface compare-at prices appears as a "was " sale, and corrupts the field for storefront feeds (Google Shopping, Facebook, Shop app), analytics, and merchants who set Compare at price manually in admin.

## Repro (code-side, `ShpfyVariantAPI.UpdateProductPrice`)
Two bulk-only paths produced `"0"`:

1. **Clearing**: when Compare at Price changed to 0 in BC, the inline GraphQL emitted `compareAtPrice: null` correctly, but the bulk JSONL fragment hard-coded `CompareAtPrice := '0'`.
2. **Defaulting**: when Compare at Price was unchanged but Price/Unit Cost moved, the bulk JSONL defaulted to `Format(ShopifyVariant."Compare at Price", 0, 9)`, which is `"0"` for the (very common) no-sale case - silently overwriting any compare-at price set in Shopify admin on every BC price sync.

The single-variant GraphQL path was fine; it never hit the bulk template.

## Fix
- `%4` in the bulk JSONL template (`ShpfyBulkUpdateProductPrice.GetInput`) now carries the entire optional `, "compareAtPrice": <value>` fragment (including the leading comma) or an empty string.
- `ShpfyVariantAPI.UpdateProductPrice` builds the fragment as:
  - `, "compareAtPrice": "<value>"` when Price < Compare at Price (a valid sale),
  - `, "compareAtPrice": null` when Compare at Price changed and is at/below Price (clear it on Shopify),
  - empty string when Compare at Price did not change in BC (omit the field, Shopify preserves its current value).
- The defaulting block that emitted `"0"` is removed.

This mirrors the non-bulk GraphQL path's semantics for `compareAtPrice`.

## Tests
Added regression tests in `ShpfyBulkOperationsTest.Codeunit.al` that call `UpdateProductPrice` directly on the bulk path (RecordCount = 100) and assert on the JSONL produced:

- `TestBulkUpdateProductPriceClearsCompareAtPriceAsNull` - covers defect 1 (must emit `null`, never `"0"`).
- `TestBulkUpdateProductPriceOmitsUnchangedCompareAtPrice` - covers defect 2 (BC Compare = 0 unchanged, only Price moved → omit, do not send `"0"`).
- `TestBulkUpdateProductPriceSendsValidCompareAtPriceAsQuoted` - guards against over-correction; valid sale price still sends as quoted decimal.
- `TestBulkUpdateProductPriceOmitsUnchangedPositiveCompareAtPrice` - guards against accidentally clearing a valid sale price during unrelated updates.

Fixes [AB#633535](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/633535)



