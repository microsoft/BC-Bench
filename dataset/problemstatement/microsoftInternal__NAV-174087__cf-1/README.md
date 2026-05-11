# Title: "Evaluation" field not saved due to workflow step order — CopyFromSegment must precede Modify
## Repro Steps:
1. Open Contacts list and select a Contact
2. Open Contact Card
3. Use "Create Interaction" action
4. Fill in Interaction Template Code, click Next twice
5. Set Evaluation to Positive
6. Click Finish
7. Check Interaction Log Entries for the Contact

Result: Evaluation field is blank in the Interaction Log Entry.

Expected: Evaluation should be "Positive" as entered in the wizard.

## Description:
Variant of NAV-174087 (L4: workflow step order). The wizard Step 4 must call CopyFromSegment(Rec) BEFORE Modify() so that segment line data (including Evaluation) is written to the Interaction Log Entry record before it is persisted. If the order is reversed (Modify first, CopyFromSegment after), the DB save happens with stale data.
Variant of NAV-174087 where the Evaluation is set to Negative instead of Positive. The fix should directly assign the Evaluation field from the segment line record to the Interaction Log Entry, rather than using the bulk CopyFromSegment call. This tests that the fix works for non-default enum values and exercises a narrower field-level persistence path.
