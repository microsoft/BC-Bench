---
bc-version: [all]
domain: performance
keywords: [readisolation, locktable, updlock, read-only, transaction-scope, isolation-level]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Prefer ReadIsolation over LockTable for read-only scenarios

## Description

`LockTable` and `ReadIsolation` solve different problems with different blast radii. Per the upstream guidance, "`LockTable` ensures that all READS against that table will happen with UPDLOCK for the remainder of the transaction." `ReadIsolation` "only pertains to the current record instance, while `LockTable` affects the lockstate of the entire transaction." `ReadIsolation` is also more expressive: it can heighten or lower the isolation level inside an already-established transaction. Reaching for `LockTable` when only a single read needs guarding therefore poisons every later read on that table — including reads in other code paths that share the transaction.

## Best Practice

For a read-only operation, or a single read that needs a higher isolation level than the surrounding transaction, set `Rec.ReadIsolation := IsolationLevel::ReadCommitted;` (or the level the call requires) immediately before the read. The hint applies only to that record instance. Save `LockTable` for code that genuinely needs every subsequent read on the table to acquire an update lock (see `findset-true-applies-updlock-on-read.md` for the alternative narrower mechanism on iterated reads).

See sample: `prefer-readisolation-over-locktable-for-reads.good.al`.

## Anti Pattern

`Rec.LockTable();` at the top of a helper that only reads, perhaps to "make sure the read is consistent". Every subsequent read on that table for the rest of the transaction acquires `UPDLOCK`, including reads from unrelated code paths fused into the same transaction. The contention surfaces in unrelated user sessions, not in the helper that introduced it.

See sample: `prefer-readisolation-over-locktable-for-reads.bad.al`.
