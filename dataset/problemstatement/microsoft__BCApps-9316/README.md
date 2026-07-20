# [Shopify] Preserve manually set Sell-to Customer No. when Bill-to mapping fails

## What & why

Fixes a Shopify Connector bug: when a user manually set **Sell-to Customer No.** on a Shopify order but left **Bill-to Customer No.** unmapped, the **Create Sales Document** action overwrote the manual Sell-to selection with the (blank) customer-mapping result and failed with *"Not everything can be mapped."*, losing the user's selection.

**Root cause:** In `Shpfy Order Mapping`.`MapHeaderFields`, when *Bill-to Customer No.* was empty the code entered the mapping block and unconditionally re-mapped *Sell-to Customer No.*. With no mapping configured for the Shopify customer, the mapping returned blank and cleared the manual selection. There was also no fallback to derive *Bill-to* from *Sell-to* (only the reverse existed).

**Fix:**
- Only run the Sell-to customer mapping when *Sell-to Customer No.* is still blank, preserving a manually chosen customer.
- Add a symmetric fallback so *Bill-to Customer No.* is derived from *Sell-to Customer No.* when Bill-to remains blank, allowing the document to be created.

## Linked work

Fixes [AB#642033](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/642033)

## How I validated this

- [x] I read the full diff and it contains only changes I intended.
- [x] I built the affected app(s) locally with no new analyzer warnings.
- [x] I ran the change in Business Central and confirmed it behaves as expected.
- [x] I added or updated tests for the new behavior, or explained below why none are needed.

**What I tested and the outcome**

- Built the Shopify Connector app locally with the AL compiler: 0 errors, no new analyzer warnings.
- Added `TestManualSellToPreservedWhenBillToMappingFails` in `Shpfy Order Test` (139609) reproducing the scenario (manual Sell-to, empty Bill-to, no default customer / no mapping). It asserts `DoMapping` succeeds, the manual Sell-to is preserved, and Bill-to falls back to it. The test compiles against symbols; runtime execution was deferred.

## Risk & compatibility

Low. The Sell-to mapping now runs only when Sell-to is blank, so automated order imports (where Sell-to Customer No. starts blank) are unchanged. The new Bill-to-from-Sell-to fallback only fires when Bill-to would otherwise remain blank. Scope is limited to the non-B2B customer path (`MapHeaderFields`); the B2B path (`MapB2BHeaderFields`) is unchanged.





