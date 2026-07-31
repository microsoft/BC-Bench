# Phase 2b — BCApps check  (optional)

Determine whether the requested change targets objects that live in a **separate BCApps
repository** rather than the extensibility surface. If so, the request belongs there.

## Status in this repo

**Disabled by default.** The eval runs against a single self-contained AL source tree
under `CODE_ROOT`; there is no separate BCApps repo to redirect to. Unless `BCAPPS_CHECK`
is explicitly enabled and a BCApps remote is configured, skip this phase: treat the result
as `{ "FoundInBCApps": false }` and continue to Phase 3.

## If enabled

With a configured BCApps remote (`BCAPPS_OWNER`/`BCAPPS_REPO`), run the original logic
against that repo using the remote code-search capability:

1. From `proposedCode` and `goal`, extract **only the direct target objects** (not
   context/callers/examples). Log: `Extracted target objects: [...]`.
2. Derive each AL filename (CamelCase + `.Type.al`).
3. Search the BCApps repo by filename (exact base-name match) or, for numeric IDs, by the
   declaration pattern (e.g. `codeunit 80`). Stop when one target is confirmed.
4. Any target confirmed → `{ "FoundInBCApps": true }`; otherwise
   `{ "FoundInBCApps": false }`.

If `FoundInBCApps` is true → set `FailureLabel: bcapps`,
`FailureReason: "target exists in BCApps"`, and go to **Phase 7**.

## Output (raw JSON)
    { "FoundInBCApps": false }
