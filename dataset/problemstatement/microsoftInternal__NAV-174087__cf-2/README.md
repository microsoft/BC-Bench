# Title: "Evaluation" field must be persisted via record trigger, not page workflow step
## Repro Steps:
1. Open Contacts list and select a Contact
2. Open Contact Card
3. Use "Create Interaction" action
4. Fill in Interaction Template Code, click Next twice
5. Set Evaluation to Positive
6. Click Finish
7. Check Interaction Log Entries for the Contact

Result: Evaluation field is blank in the Interaction Log Entry.

Expected: Evaluation should be "Positive" — persisted automatically via an OnModify trigger on the Interaction Log Entry table, independent of the page wizard workflow.

## Description:
Variant of NAV-174087 (L3: trigger-based persistence). Instead of relying on the page wizard Step 4 to explicitly call CopyFromSegment, the Evaluation field should be persisted through a record lifecycle trigger (OnModify) on the Interaction Log Entry table. This shifts persistence responsibility from the UI workflow layer to the data layer, making it robust against page flow changes.

## Description:
Variant of NAV-174087 where the test additionally verifies that the Initiation Type field is persisted alongside Evaluation. This requires the full CopyFromSegment call rather than a narrower field-level fix, testing that the complete segment data flows through the record lifecycle into the Interaction Log Entry.
