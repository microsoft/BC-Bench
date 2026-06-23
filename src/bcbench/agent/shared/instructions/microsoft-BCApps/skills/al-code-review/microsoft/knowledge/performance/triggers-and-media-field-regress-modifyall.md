---
bc-version: [all]
domain: performance
keywords: [modifyall, deleteall, regression, triggers, media, getglobaltabletriggermask, subscriber]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Triggers, subscribers, and media fields can silently regress ModifyAll / DeleteAll

## Description

`ModifyAll` and `DeleteAll` usually execute as single SQL statements, but the platform falls back to a fetch-then-row-by-row loop under specific conditions. Per the upstream guidance, the regression is triggered by any of: global database triggers defined via `GetGlobalTableTriggerMask` or `GetDatabaseTableTriggerSetup` (so that `OnDatabaseDelete`/`OnGlobalDelete` must run); event subscribers on the table's `OnBeforeDelete`/`OnAfterDelete` (for `DeleteAll`) or `OnBeforeModify`/`OnAfterModify` (for `ModifyAll`); or "adding a Media or MediaSet table field to either the table or table extension." Each of these forces the platform to materialize each affected row in AL.

## Best Practice

Before introducing any of the above on a table — a global trigger registration, a `Modify`/`Delete` subscriber, a media or media-set field — note every `ModifyAll`/`DeleteAll` that targets the table and assess whether the regression cost is acceptable. The upstream guidance is explicit: "There should be a very good reason for doing any of the above since they will significantly regress performance of `ModifyAll` and/or `DeleteAll`." Once a table has regressed, multiple `ModifyAll` calls each iterate the rows themselves, so consolidating to one explicit `FindSet`+`Modify` loop becomes faster than chaining several `ModifyAll` calls.

## Anti Pattern

Adding a media field to a hot table — or subscribing to its modify/delete events from a generic logging codeunit — without auditing the bulk-write call sites. The schema change is mechanical; the performance change is invisible at the call site and only surfaces when a previously fast `ModifyAll` starts paying the per-row trigger cost in production. The mirror anti-pattern is chaining several `ModifyAll` calls on a table that has already regressed; each one re-iterates the same rows.
