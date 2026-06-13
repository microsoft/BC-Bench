---
bc-version: [all]
domain: performance
keywords: [table-size, hot-table, ledger-entry, item, customer, sales-line, scale]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Production-scale tables warrant concrete performance analysis

## Description

Some Business Central tables routinely reach sizes where access patterns matter much more than they do on a generic table. The upstream review guidance lists ten of them with P95 row counts: Item (~800k), Customer (~800k), Item Ledger Entry (~10M), Value Entry (~10M), G/L Entry (~10M), VAT Entry (~10M), Customer Ledger Entry (~10M), Vendor Ledger Entry (~10M), Sales Invoice Header (~300k), and Sales Invoice Line (~3M). These figures are not platform constants — they are the volumes a reviewer should assume when judging a change.

## Best Practice

For any code change that touches one of these tables, do not approve the pattern on intuition. Walk through the SQL the change implies (one query? one per row? one per chunk?), the memory it allocates (a `List` per row?), and the CPU work per row, against the row counts above. Smaller tables can tolerate a sub-optimal access pattern; these cannot. The rest of this domain — `apply-filters-before-iterating.md`, `use-setloadfields-for-partial-records.md`, `avoid-calcfields-in-loops.md`, `pair-findset-with-next-loop.md`, `avoid-get-inside-loop-on-persistent-tables.md` — exists primarily so that code touching these tables stays on the safe side of each rule.

## Anti Pattern

Generalizing from a unit test or a development tenant. A `FindSet` loop with a per-row `CalcFields` may execute in milliseconds against a few thousand rows on a developer's machine and become a multi-minute table scan against ten million Value Entry rows in production. Reasoning about performance from the dev-tenant timing instead of the production volume is the single most common way a regression ships.
