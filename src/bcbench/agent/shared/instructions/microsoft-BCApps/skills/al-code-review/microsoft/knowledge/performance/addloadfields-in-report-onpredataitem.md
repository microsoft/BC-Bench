---
bc-version: [all]
domain: performance
keywords: [report, addloadfields, onpredataitem, dataitem, partial-record, layout]
technologies: [al]
countries: [w1]
application-area: [all]
---

# In reports, declare the fields the layout needs with AddLoadFields

## Description

Reports iterate dataitems on potentially large source tables and pipe rows into a layout. The partial-record optimization is the same idea as `use-setloadfields-for-partial-records.md`, but the API is different: per the upstream guidance, "for reports, use `AddLoadFields()` in `OnPreDataItem` trigger to add fields needed by the layout." `AddLoadFields` is additive — call it for each field the layout consumes — and runs once per dataitem before iteration begins.

## Best Practice

In each dataitem's `OnPreDataItem` trigger, list the columns the layout binds to via `AddLoadFields(<field>, <field>, ...)`. The platform then materializes only those columns per row. Treat the layout column list as the spec: every column the layout uses must be added; columns the layout does not use should not be added.

See sample: `addloadfields-in-report-onpredataitem.good.al`.

## Anti Pattern

Relying on the dataitem's default to load every field. On a report bound to a ledger-scale table this transfers an entire row per iteration, of which the layout reads a fraction.

See sample: `addloadfields-in-report-onpredataitem.bad.al`.
