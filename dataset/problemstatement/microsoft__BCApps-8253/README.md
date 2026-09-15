# Title: [Subcontracting] Standard Task not propagated from Routing to Prod. Order Routing or Subcontracting Worksheet; prices not picked up
## Repro Steps:
**Issues:**

1.  **Standard Task not propagated from Routing:** When a routing line has a Standard Task set, that value is not copied to the corresponding Prod. Order Routing line.
2.  **Standard Task not propagated to Subcontracting Worksheet:** The Standard Task from the routing line is also not populated in the Subcontracting Worksheet when lines are pulled.
3.  **Standard Task not editable in Subcontracting Worksheet:** Even if the field were present, it is not editable in the Subcontracting Worksheet, preventing manual correction.
4.  **Prices not picked up:** If the user has configured prices tied to a Standard Task, those prices are not used because the Standard Task is missing from the subcontracting flow.

**Expected:** Standard Task should be propagated from Routing to Prod. Order Routing and to the Subcontracting Worksheet. The field should be editable in the worksheet. Prices bound to Standard Task should be applied correctly.

## Description:


## Hints

### Repro Steps Clarity Score: 6/10
+Specificity +Determinism
-Missing environment -Unverified UI references
-Missing data values (no concrete Standard Task / item / routing combo named in the bug)

The bug enumerates 4 related symptoms but provides no concrete data combination. Steps below pick concrete demo values and a sequenced repro for each symptom.
----
### Detailed Repro Steps
#### Environment
- Build: Master — Subcontracting feature dev build (target branch master).
- Localization: W1 (any localization should reproduce).
- Functional area: SCM / Manufacturing — Subcontracting (Standard Task propagation, Subcontracting Worksheet editing, Subcontracting price lookup).

#### Prerequisites
- Subcontracting feature available with: a Subcontractor vendor, a Subcontracting Work Center, an item with a Production BOM and a Routing.
- A Standard Task code defined (e.g., STD-PAINT) — choose Search > Standard Tasks > + New to add one.
- A Routing that includes the Subcontracting Work Center, with at least one Routing Line whose Standard Task Code is set to STD-PAINT.
- A Subcontracting price (e.g., on the Standard Task card or on the Subcontracting Work Center / Subcontractor Vendor) that is specifically tied to Standard Task STD-PAINT (so that when STD-PAINT is present on the line, the price applies; when absent, it does not).
- A Released Production Order created from the manufacturing item with the routing above.

#### Steps — Issue 1: Routing → Prod. Order Routing propagation
1. Choose Search > Routings, open the routing used by the manufacturing item, and confirm the Subcontracting routing line has Standard Task Code = STD-PAINT.
2. Choose Search > Released Production Orders, open the order created in prerequisites.
3. Drill into Lines > Routing to open Prod. Order Routing.
4. Observe Issue 1: the Prod. Order Routing line corresponding to the Subcontracting operation has Standard Task Code = blank (it was not copied from the source Routing).

#### Steps — Issue 2: Routing → Subcontracting Worksheet propagation
5. Choose Search > Subcontracting Worksheet, choose the related link.
6. Choose Calculate Subcontracts…, accept defaults, run.
7. Observe Issue 2: the worksheet line for the production order's subcontracting operation has Standard Task Code = blank, even though the routing line has STD-PAINT set.

#### Steps — Issue 3: Standard Task not editable in Subcontracting Worksheet
8. On the worksheet line from step 7, attempt to set Standard Task Code = STD-PAINT either by typing or via the lookup.
9. Observe Issue 3: the field is read-only / not editable, so the missing value cannot be corrected manually before Carry Out Action Message.

#### Steps — Issue 4: Prices not picked up because Standard Task is missing
Without correcting the Standard Task (since you cannot, per Issue 3), choose Carry Out Action Message… to create the Subcontracting Purchase Order.
Open the resulting Subcontracting Purchase Order line.
Observe Issue 4: the Direct Unit Cost / line price is the work-center default price, not the price tied to Standard Task STD-PAINT. Because the Standard Task is missing from both the routing line and the worksheet, the price-lookup step never matches the standard-task-specific price and the wrong (or default) price is applied.

#### Expected Result
- Routing → Prod. Order Routing → Subcontracting Worksheet → Subcontracting Purchase Order all preserve Standard Task Code end-to-end.
- The Standard Task Code field is editable in the Subcontracting Worksheet so users can correct or override.
- Subcontracting price lookup uses the Standard Task Code as a key, so prices defined per Standard Task are applied to the resulting PO line.

#### Actual Result
- Standard Task Code is dropped at the Routing → Prod. Order Routing step, and remains missing on the Subcontracting Worksheet and the resulting Subcontracting PO. Prices tied to Standard Task are therefore never selected.

#### Notes
- Severity 3, Priority 2. Issue type: Code Defect. Found by Manual Testing: Other Test Pass on 2026-04-30 by Chethan Thopaiah.
- Likely fix surfaces:
    - Refresh production order routine (Codeunit "Prod. Order Routing Mgt." or equivalent) — copy Standard Task Code from Routing Line to Prod. Order Routing Line.
    - Calculate Subcontracts (Codeunit "Subcontracting Worksheet Mgt." / similar) — copy Standard Task Code from Prod. Order Routing Line into the worksheet line.
    - Page extension on Subcontracting Worksheet — set the Standard Task Code field Editable = true (subject to UX review).
    - Subcontracting price lookup — extend the price-source lookup to include Standard Task Code as a key so prices tied to a Standard Task are matched.
- Sibling Subcontracting bugs that touch the routing → worksheet → PO chain: #633223, #633224, #633227, #633228, #633229.

[AI-REPRO] score=6 | workItemId=633226 | generated=2026-04-30 | sources=repro_steps,documentation
