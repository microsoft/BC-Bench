---
bc-version: [all]
domain: privacy
keywords: [data-migration, hybridsl, hybridgp, hybridbc, destination-classification, ssn, tin]
technologies: [al]
countries: [w1]
application-area: [all]
---

# In data migration code, classify the destination — not the migration itself

## Description

Migration codeunits such as `HybridSL`, `HybridGP`, and `HybridBC` exist to copy sensitive data — TINs, Federal IDs, social security numbers, financial records — from a source system into Business Central. The fact that PII flows through these codeunits is the entire point of their existence, not a defect. The privacy concern is whether the destination field where the data lands carries the correct `DataClassification`. If it does, the migration is doing its job; if it doesn't, the right fix is on the destination table field, never on the migration code that writes to it.

## Best Practice

When reviewing a migration codeunit, trace each `Dest."<Field>" := Source."<Field>"` assignment to the destination field's `DataClassification`. Confirm that fields receiving PII (SSNs, Federal IDs, customer names, addresses) are classified `EndUserIdentifiableInformation` or `CustomerContent` as appropriate — and not left as `SystemMetadata` or `ToBeClassified`.

## Anti Pattern

Flagging the migration code itself for "processing sensitive data" or recommending that it filter, hash, or skip PII fields — these tables exist to migrate that data. The actionable finding is always on the destination field's classification, not on the migration's assignment statement.
