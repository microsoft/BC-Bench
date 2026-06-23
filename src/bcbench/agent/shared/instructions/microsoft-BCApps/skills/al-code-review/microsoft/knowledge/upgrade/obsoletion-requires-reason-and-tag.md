---
bc-version: [all]
domain: upgrade
keywords: [obsolete-state, obsolete-reason, obsolete-tag, deprecation, metadata]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Mark obsolete elements with `ObsoleteState`, `ObsoleteReason`, and `ObsoleteTag`

## Description

When a procedure, field, table, page, or enum value is being retired, AL requires three pieces of metadata to declare the deprecation:

- `ObsoleteState` — `Pending` while the element still exists but is being phased out, `Removed` once it should no longer be used.
- `ObsoleteReason` — a short human-readable string explaining what to use instead. Tooling and downstream consumers surface this when warning callers.
- `ObsoleteTag` — a stable version-like marker (typically the release version in which the deprecation was introduced, e.g. `'22.0'`).

Omitting `ObsoleteReason` or `ObsoleteTag` leaves consumers with `ObsoleteState = Pending` but no guidance and no traceability. Declaring `ObsoleteState = Removed` without a reason or tag is the same failure with a stronger blast radius.

## Best Practice

Every obsoleted element carries all three properties together. The reason names the replacement explicitly; the tag is the version in which the deprecation was introduced and stays stable for the life of the deprecation.

See sample: `obsoletion-requires-reason-and-tag.good.al`.

## Anti Pattern

Setting only `ObsoleteState = Pending;` (or `Removed`) without `ObsoleteReason` and `ObsoleteTag`. Callers see a warning with no explanation, and the deprecation cannot be tracked by version.

See sample: `obsoletion-requires-reason-and-tag.bad.al`.

## See also

- `obsolete-pending-to-removed-staging.md` — when to advance `Pending` to `Removed` and write upgrade code.
