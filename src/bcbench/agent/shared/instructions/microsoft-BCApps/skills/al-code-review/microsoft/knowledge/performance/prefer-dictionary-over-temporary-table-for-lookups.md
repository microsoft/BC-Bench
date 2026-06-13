---
bc-version: [all]
domain: performance
keywords: [dictionary, temporary-table, lookup, o-of-1, key-lookup]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Prefer a Dictionary over a temporary table for pure lookups

## Description

A temporary table supports a full record API — filters, iteration, multi-field keys — but a pure key→value lookup pays for plumbing it does not use. Per the upstream guidance, "if a temporary table record is ONLY used as a lookup table, it is faster to use a dictionary which supports O(1) lookups instead of O(lg n) for temporary tables." The Dictionary type has no record machinery to traverse; the key hash answers the lookup directly.

## Best Practice

When the use of a temp record is "set a key, see if the row exists, read a single value", switch to `Dictionary of [Key, Value]`. Use the temp-table form when the use genuinely needs filtering, iteration in a specific order, or a multi-field key. Compatibility with code that expects a `Record` parameter is a real reason to keep the temp table; performance alone, on a pure lookup, is not.

## Anti Pattern

A temp `Record` declared, populated row by row, then queried with `SetRange(KeyField, X); if Find('=') then Value := Rec.ValueField;`. The lookup hashes the key behind the scenes and does the same work a `Dictionary` would, plus the per-row record overhead. The pattern often appears because the author originally needed iteration and the iteration was later removed without revisiting the data structure.
