---
bc-version: [all]
domain: performance
keywords: [setcurrentkey, key, index, filter, sort]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Pick a key whose fields cover the filter and sort with SetCurrentKey

## Description

The platform chooses a key for each record access. When the filters or required sort do not match the primary key — or any non-explicit choice — the query may run against a key that does not cover the filter columns. Per the upstream guidance, "Use `SetCurrentKey()` to select the most efficient key for your filters" and "match key fields to your filter/sort requirements." Filtering on fields that are not in any key is flagged as bad — there is no index to ride and the access ends up reading more than necessary.

## Best Practice

When the access pattern is anything other than primary-key lookup, look at the filters and the desired sort, then either pick an existing key whose leading fields cover them and call `SetCurrentKey(...)`, or declare a new key on the table for the pattern. Match leading fields first — a key starting with `"Document Type", "Document No.", "Line No."` serves a filter on those three; a key starting with `"Line No."` does not.

See sample: `setcurrentkey-aligns-key-with-filters.good.al`.

## Anti Pattern

Applying filters on fields that no key indexes, leaving the platform to read more than it should. The query produces the right answer; the cost surfaces only at production volume. The mirror case is forgetting `SetCurrentKey` when the wanted sort differs from the primary key — the iteration may then be sorted in memory after a wider read than necessary.
