---
bc-version: [all]
domain: performance
keywords: [textbuilder, string-concatenation, loop, append, immutable-text]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Use TextBuilder for many string concatenations, especially inside loops

## Description

AL `Text` is immutable: each `Result += Piece;` allocates a new buffer and copies the previous content into it. Inside a loop the work is quadratic in the number of pieces. `TextBuilder` is the AL primitive designed for the pattern — per the upstream guidance, "Use `TextBuilder` when concatenating many strings together (for example inside loops)." Its `Append` mutates a growable internal buffer; `ToText()` materializes the final string once at the end.

## Best Practice

When a procedure assembles a string from many fragments — joining row data into a CSV, accumulating a log buffer, formatting a multi-line message inside a loop — declare a `TextBuilder` local, call `Append` per fragment, and call `ToText()` after the loop. For a fixed number of small fragments, `StrSubstNo` remains the right tool; the rule targets the loop case.

## Anti Pattern

`if Customer.FindSet() then repeat Csv += Customer."No." + ',' + Customer.Name + '\n'; until Customer.Next() = 0;` — every iteration reallocates and copies the entire string built so far. On a few hundred customers the cost is invisible; on the production-scale table list (`production-scale-tables-warrant-extra-analysis.md`) it dominates the loop.
