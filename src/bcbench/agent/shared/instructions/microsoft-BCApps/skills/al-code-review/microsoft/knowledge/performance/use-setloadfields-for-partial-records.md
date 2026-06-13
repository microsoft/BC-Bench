---
bc-version: [all]
domain: performance
keywords: [setloadfields, partial-record, normal-field, flowfield, get, findset]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Use SetLoadFields to load only the fields the code reads

## Description

`SetLoadFields(...)` declares the subset of normal fields the next read should materialize, "reducing data read and transfer thereby improving performance significantly." Per the upstream guidance, "the gains scale with the amount of rows read, so for loops that read many rows `SetLoadFields` is even more important." Primary-key fields, `SystemId`, and system audit fields are loaded automatically, "and fields that are filtered on are also automatically included" — those do not need to appear in the list. `SetLoadFields` only affects `FieldClass = Normal`; it does not narrow FlowFields or FlowFilters.

## Best Practice

Before a `Get`, `FindSet`, or `FindFirst` that the procedure follows by reading only a handful of the table's fields, call `SetLoadFields` listing exactly those fields. The pattern `SetLoadFields(...); if Record.Get(...) then ...` is the upstream-endorsed shape. Skip `SetLoadFields` when the table has few fields (under ten), when the code reads most of them (above 60 %), when the loop runs ten or fewer iterations, or when the table is exempt for other reasons (`singleton-setup-tables-need-no-access-optimization.md`, `temporary-tables-have-no-database-cost.md`). For report dataitems, use `AddLoadFields` in `OnPreDataItem` instead (see `addloadfields-in-report-onpredataitem.md`).

See sample: `use-setloadfields-for-partial-records.good.al`.

## Anti Pattern

Loading a wide table and reading one field per row in a loop. The bytes transferred per row are dominated by the columns the procedure does not touch; the SQL query selects them anyway. The same applies to a single `Get` on a wide table — the platform reads the whole row when a single field would have sufficed.

See sample: `use-setloadfields-for-partial-records.bad.al`.
