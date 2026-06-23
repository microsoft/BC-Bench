---
bc-version: [all]
domain: performance
keywords: [modifyall, deleteall, bulk, loop, modify, set-based]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Use ModifyAll / DeleteAll instead of per-row Modify / Delete in a loop

## Description

`ModifyAll` and `DeleteAll` are the bulk APIs. Per the upstream guidance, they "execute as single SQL statements" when the table supports it — one round-trip updates or deletes every row in the filtered set. The anti-pattern is the loop equivalent: `FindSet` followed by per-row `Modify`/`Delete`, where the runtime issues one write per row. On a production-scale table the difference is the difference between a single statement and N statements.

## Best Practice

When the loop body does nothing more than assign a constant value (or a value computed once) to one or more fields, replace the loop with `ModifyAll("Field 1", Value1)` — and chain additional `ModifyAll` calls for additional fields. The same shape applies to `DeleteAll`. Be aware that the bulk APIs can regress to row-by-row execution for tables with certain trigger or media-field configurations (see `triggers-and-media-field-regress-modifyall.md`); when that regression applies, multiple `ModifyAll` calls become more expensive than one manual loop, so the choice is conditional, not absolute.

See sample: `prefer-modifyall-over-per-row-modify.good.al`.

## Anti Pattern

`if SalesLine.FindSet() then repeat SalesLine.Validate("Unit Price", NewPrice); SalesLine.Modify(true); until SalesLine.Next() = 0;` — N writes when one would do. The pattern is easy to introduce when the loop initially does per-row computation and is later simplified to assign a constant; the loop scaffolding survives the simplification.

See sample: `prefer-modifyall-over-per-row-modify.bad.al`.
