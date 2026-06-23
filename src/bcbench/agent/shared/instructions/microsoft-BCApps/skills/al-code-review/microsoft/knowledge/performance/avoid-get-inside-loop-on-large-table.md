---
bc-version: [all]
domain: performance
keywords: [n-plus-one, get, findfirst, loop, inner-lookup, large-table]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Avoid Get / FindFirst inside a loop on a large inner table

## Description

A `Get` or `FindFirst` against a different record inside a loop body produces one database round-trip per iteration — the classic N+1 pattern. Per the upstream guidance, "Flag when a `Get()`/`FindFirst()` is called inside a loop for each record — this creates N+1 database round-trips." The cost only matters when the inner table is meaningful: lookups against temporary tables, singleton setup tables, enum-mapping tables, permission objects, or Role IDs are bounded and safe. The pattern to catch is the inner lookup that hits a production-scale table for every outer row.

## Best Practice

When the loop needs values from another record, lift the lookup out of the loop if the rows can be collected up front, or apply `SetLoadFields` so each inner read transfers only the columns the loop actually uses (see `use-setloadfields-for-partial-records.md`). When the inner record is small or bounded, leave the call site alone — the rule targets large-table inner lookups specifically.

See sample: `avoid-get-inside-loop-on-large-table.good.al`.

## Anti Pattern

Iterating BOM lines and calling `Item.Get(BOMLine."No.")` per row to read a costing method, with no `SetLoadFields` on `Item`. Each iteration issues one query against Item (~800k rows) and pulls the entire row to read two fields. The fix is `Item.SetLoadFields("Costing Method", "Standard Cost");` ahead of the loop — still N reads, but each one transfers only the needed columns.

See sample: `avoid-get-inside-loop-on-large-table.bad.al`.
