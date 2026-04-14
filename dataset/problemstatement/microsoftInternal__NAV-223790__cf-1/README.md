# Title: "Calculate Regenerative Plan" does not plan component — LLC updated at planning phase
## Repro Steps:
Same as NAV-223790 base repro, except:
- Stockkeeping Unit fields are set via direct record modification (bypassing page OnValidate triggers)
- Production BOM No. is assigned directly rather than through the SKU Card page

This means the OnValidate trigger on "Production BOM No." never fires, and LLC is never updated during setup.

## Description:
Variant of NAV-223790 (L3: trigger lifecycle change). The test bypasses SKU page validation so the OnValidate trigger for "Production BOM No." never fires. The fix ensures LLC is calculated at planning execution time (OnPreReport of Calculate Plan - Plan. Wksh.), iterating over all SKUs with Production BOM assignments and computing LLC before BOM expansion begins. This shifts LLC freshness responsibility from data mutation time to execution time.
