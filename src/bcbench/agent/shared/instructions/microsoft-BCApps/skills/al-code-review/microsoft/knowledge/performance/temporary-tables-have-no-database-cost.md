---
bc-version: [all]
domain: performance
keywords: [temporary-table, in-memory, findset, findfirst, get, no-db-cost]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Temporary tables are in-memory; access-pattern rules do not apply

## Description

A record declared `Temporary` (or a page with `SourceTableTemporary = true`) lives entirely in memory; reads and writes never reach SQL. Per the upstream guidance, "any access pattern (FindSet, FindFirst, Get, loops) on temp tables is acceptable — they are in-memory and fast." The rules in the rest of this domain — partial loading, bulk operations, N+1 detection, `IsEmpty` over `Count` — exist to avoid database round-trips that a temporary table does not perform.

## Best Practice

Recognize the `Temporary` property (on a record variable, table declaration, or page's `SourceTableTemporary`) and exempt the code from access-pattern flags. The `SetLoadFields`/`FindSet` discipline that matters for `Customer` does not matter for a temporary `Customer` variable used as a working set. The interesting performance question on a temp table is volume in memory, not query plan.

## Anti Pattern

Flagging a temporary table's `FindFirst` inside a loop, or a temporary table without `SetLoadFields`, as a performance issue. The recommendation produces no measurable gain and obscures genuine issues elsewhere in the same review.
