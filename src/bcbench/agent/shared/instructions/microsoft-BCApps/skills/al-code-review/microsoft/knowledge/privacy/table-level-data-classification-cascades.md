---
bc-version: [all]
domain: privacy
keywords: [data-classification, table-level, inheritance, override, cascading]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Table-level DataClassification cascades to every field unless overridden

## Description

`DataClassification` may be set at the table level. When it is, every field in the table inherits that classification and individual fields do not need their own `DataClassification` property. The cascade is the platform's intended way of classifying tables whose fields are homogeneous — for example, a system configuration log whose every column is `SystemMetadata`. A field only needs its own classification when its content genuinely differs from the table's default and the inherited value would be wrong.

## Best Practice

Set `DataClassification` once at the table level whenever every field in the table shares the same classification. Omit field-level `DataClassification` properties in that case. Override only on the specific fields whose data class differs from the table's — for example, a `SystemMetadata` audit table that nonetheless captures a `CustomerContent` value somewhere.

See sample: `table-level-data-classification-cascades.good.al`.

## Anti Pattern

Flagging individual fields for "missing `DataClassification`" when the table declares one — the inheritance is the correct, intentional pattern. The mirror anti-pattern is repeating the same `DataClassification` on every field of a table that already declares it at the table level; the property is redundant and adds nothing the platform did not already know.
