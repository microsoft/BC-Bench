# Costing / Inventory Valuation Bug-Fix Playbook (Business Central)
> **How to use this guide — read first.** This is a playbook of practical hints, not a source of indisputable truth. Don't spend time confirming or refuting the statements here, and don't go looking for a pull request, work item, commit, author, or date behind any recommendation. Use it as a helper — apply what fits the bug in front of you, and use your own judgment for the specifics.


> Domain knowledge for the automated bug-fix agent working on **Costing / Inventory
> Valuation** bugs in `this repo` (base-app W1 + localized layer copies):
> item costing, cost adjustment, Value Entries, item application, exact-cost
> reversing, revaluation, item charges, additional-reporting-currency costing,
> manufacturing cost shares, and inventory valuation reports.
>
> This is **not** an AL language guide. It only carries costing/valuation-specific
> knowledge and concrete lessons — what worked and what did not — from past fixes
> and reviews. Generic AL rules, style advice, analyzer findings, CI hygiene, and
> anything the compiler/publisher catches on its own are deliberately left out.

---

## §0 The area in one picture

Costing is the ledger layer underneath inventory posting. The same defect often
appears as a purchase/posting bug, an undo bug, a report bug, or a G/L
reconciliation bug, but the invariant is the same:

1. **Item Ledger Entry (ILE, table 32)** records quantity and application state.
   It carries entry numbers, invoiced quantity, exact-cost fields, and summary
   cost FlowFields.
2. **Value Entry (table 5802)** records the value attached to an ILE. It is the
   first place to check when a user says inventory value, expected/actual cost,
   item-charge cost, ACY amount, valuation date, or revaluation is wrong.
3. **Item Application Entry (table 339)** links inbound and outbound ILEs. FIFO,
   average, specific costing, exact-cost reversing, and undo paths depend on this
   chain staying correct.
4. **Cost adjustment** reopens the chain after posting. It marks entries to adjust,
   calculates average/standard/FIFO effects, creates adjustment Value Entries, and
   later posts the cost to G/L.
5. **Reports** (`Inventory Valuation`, `Cost Shares Breakdown`, Power BI report
   entry points) should read the same Value Entry/ILE truth without losing filters,
   event semantics, or amount formatting.

**First classify the bug by ledger effect, not by UI entry point.** A purchase
invoice defect can be an item-charge Value Entry defect. A currency
posting defect can be an inventory valuation/G/L reconciliation defect. A report
modernization can silently bypass the old Value Entry filters that extensions
relied on.

### Key objects you will keep meeting (current IDs)

IDs below are current for the costing and inventory valuation area. Most objects are base app; several localized layers carry byte-for-
byte or near-byte-for-byte copies of posting code.

| Object | Type | Current ID | Main path | Why it matters |
|---|---|---:|---|---|
| `Item` | table | **27** | W1 BaseApp Inventory/Item | Costing method, unit/standard cost, inventory value zero, FlowFields. |
| `Item Ledger Entry` | table | **32** | W1 + layer copies | Quantity, invoiced quantity, exact-cost/application state, ILE summary costs. |
| `Value Entry` | table | **5802** | W1 + layer copies | Actual/expected cost amounts, ACY amounts, valuation date, item-charge marker. |
| `Item Application Entry` | table | **339** | W1 + layer copies | Cost application chain, exact-cost reversing, unapply/undo. |
| `Item Application Entry History` | table | **343** | W1 | Historical application trace. |
| `Item Journal Line` | table | **83** | W1 + layer copies | Posting input for CU22; source currency and cost fields are read here. |
| `Item Jnl.-Post Line` | codeunit | **22** | W1 + APAC/CH/ES/IT/RU copies | Creates ILE/Value Entries; ACY costing fixes landed here. |
| `Purch.-Post` | codeunit | **90** | W1 + many layer copies | Posts item-charge Value Entries through receipt distribution paths. |
| `Undo Posting Management` | codeunit | **5817** | W1 | Shared undo posting; owns `PostItemJnlLineAppliedToList`. |
| `Undo Sales Shipment Line` | codeunit | **5815** | W1/RU | Drop-shipment item-application unapply seam. |
| `Undo Purchase Receipt Line` | codeunit | **5813** | W1 | Purchase exact-cost reversing/undo entry point. |
| `Undo Return Shipment Line` | codeunit | **5814** | W1 | Return-side undo. |
| `Undo Transfer Shipment` | codeunit | **9030** | W1 | Transfer undo path; review asked for direct coverage when errors changed. |
| `Inventory Adjustment` | codeunit | **5895** | W1 + APAC/RU copies | Cost-adjustment implementation behind the interface. |
| `Inventory Adjustment Handler` | codeunit | **5894** | W1 | Orchestrates adjustment runs. |
| `ItemCostManagement` | codeunit | **5804** | W1/APAC/RU copies | Average/precise cost calculation and open inbound ILE filtering. |
| `Cost Adjustment Params Mgt.` | codeunit | **5824** | W1 | Parameterization around adjustment runs. |
| `Inventory Posting To G/L` | codeunit | **5802** | W1 | Posts cost adjustment/value entries to G/L. |
| `Post Inventory Cost to G/L` | report | **1002** | W1 | Batch report for inventory cost to G/L. |
| `Post Inventory Cost to G/L` | codeunit | **2846** | W1 | Codeunit wrapper for the same posting. |
| `Adjust Cost - Item Entries` | report | **795** | W1 | User-facing cost adjustment run. |
| `Cost Adjustment Overview` | page | **5801** | W1 | Cost-adjustment page/actions. |
| `Avg. Cost Adjmt. Entry Point` | table | **5804** | W1 | Average-cost valuation-date entry points. |
| `Avg. Cost Adjmt. Entry Points` | page | **5815** | W1 | Diagnostic/user view of average-cost entry points. |
| `Average Cost Calc. Overview` | table/page | **5847** | W1 | Average-cost diagnostic buffer. |
| `Inventory Adjmt. Entry (Order)` | table | **5896** | W1 | Manufacturing/order cost adjustment buffer. |
| `Inventory Valuation` | report | **1001** | W1 | Main W1 valuation report; existing Value Entry events matter. |
| `Inventory Valuation` | report | **10139** | NA | NA copy with separate event parity needs. |
| `Cost Shares Breakdown` | report | **5848** | W1 | Manufacturing cost-share report; WIP/filter/event bugs. |
| `Standard Cost Worksheet` | table/page | **5841** | W1 | Standard-cost worksheet data and UI. |
| `Calculate Standard Cost` | codeunit | **5812** | W1 | Standard-cost calculation engine. |
| `Standard Cost Worksheet` | report | **5855** | W1 | Standard-cost calculation/update report. |
| `Calculate Inventory Value` | report | **5899** | W1 | Revaluation journal population. |
| `Revaluation Journal` | page | **5803** | W1 | Revaluation entry point. |
| `Item Charge` | table | **5800** | W1 | Item-charge master. |
| `Item Charge Assignment (Purch)` | table/page | **5805** | W1 | Purchase item-charge assignment and posted-cost distribution. |
| `G/L - Item Ledger Relation` | table/page | **5823** | W1 | Reconciliation link from inventory value to G/L. |
| `Invt. Posting Buffer` | table | **48** | W1 | Cost-to-G/L staging buffer. |
| `Inventory Setup` | table | **313** | W1 | Automatic/expected cost posting, average-cost setup. |
| `Stockkeeping Unit` | table | **5700** | W1 | SKU-level standard/unit costs. |
| `Capacity Ledger Entry` | table | **5832** | W1 | Manufacturing cost-share capacity cost source. |
| `Prod. Order Line` | table | **5406** | W1 | Production item/source for WIP and standard-cost cases. |
| `Purch. Rcpt. Line` | table | **121** | W1 | Receipt-line source for item-charge Value Entries. |
| `Purchase Line` | table | **39** | W1 | Charge-assignment target line and receipt state. |

### Reliable markers and fields

Use these fields to reason about the defect. Do not replace them with nearby
fields unless the current fix proves the nearby field is the correct one.

| Table | Field(s) | Current IDs | Rule |
|---|---|---:|---|
| `Value Entry` | `"Item Ledger Entry No."`, `"Valued Quantity"`, `"Invoiced Quantity"` | 11, 12, 14 | A cost fix is not proved by existence of a Value Entry. Prove the entry is on the right ILE and has the right valued/invoiced quantity. An earlier fix caught this. |
| `Value Entry` | `"Cost Amount (Actual)"`, `"Cost Amount (Expected)"` | 43, 151 | Actual vs expected legs can need separate formulas and tests. An earlier fix landed only after both receipt and invoice legs were asserted. |
| `Value Entry` | `"Cost Amount (Actual) (ACY)"`, `"Cost Amount (Expected) (ACY)"` | 68, 156 | ACY inventory value must reconcile with G/L Additional-Currency Amount when document currency = ARC. We hit this before. |
| `Value Entry` | `"Expected Cost"`, `"Item Charge No."`, `"Partial Revaluation"`, `"Valuation Date"` | 98, 99, 102, 104 | These separate expected/actual, item-charge, partial-revaluation, and valuation-date paths. Test the branch you touch. |
| `Item Ledger Entry` | `"Invoiced Quantity"`, `"Applies-to Entry"`, `"Completely Invoiced"`, `"Applied Entry to Adjust"` | 14, 28, 5800, 5802 | Partial invoicing and exact-cost/application fixes should use state that remains valid until fully invoiced. An earlier fix changed the lookup from `Invoiced Quantity = 0` to `Completely Invoiced = false`. |
| `Item Ledger Entry` | `"Cost Amount (Expected)"`, `"Cost Amount (Actual)"`, ACY variants | 5803, 5804, 5806, 5807 | These are summary amounts. Trace back to Value Entries when the amount is wrong. |
| `Item` | `"Costing Method"`, `"Unit Cost"`, `"Standard Cost"`, `"Inventory Value Zero"` | 21, 22, 24, 5409 | Costing method drives which application/adjustment rule is in play. |
| `Inventory Setup` | `"Automatic Cost Adjustment"`, `"Expected Cost Posting to G/L"`, `"Average Cost Calc. Type"`, `"Average Cost Period"` | 30, 5800, 5804, 5805 | Average/expected cost behavior depends on setup; do not hard-code a single tenant shape. |
| `Item Charge Assignment (Purch)` | quantity/amount assignment fields | table 5805 | For item charges, the invariant includes both posted Value Entry and `Qty. Assigned = Quantity Invoiced` on the charge line, as shown by earlier fixes. |

---

## §1 The loop that worked

1. **Start from the posted ledger symptom.** Identify the exact ILE and Value Entry
   that should change. For reports, identify the Value Entry filter/sum the report
   used before the change. An earlier report change was risky because the new FlowField
   path bypassed old `Value Entry` filter events.
2. **Classify the branch: actual vs expected, direct item vs item charge, W1 vs
   localized layer, receipt vs invoice, single receipt vs partial receipts.** Most
   bad fixes covered the easy branch and missed the sibling branch.
3. **Find the analogous correct path and mirror it.** `PostItemChargePerRcpt` was
   the model for separately invoiced charges in an earlier fix. Existing W1
   `CalcPosShares()` was the model the APAC copy failed to reach in an earlier fix.
4. **When there are layer copies, patch and test the copies intentionally.** CU22
   ACY logic existed in APAC/CH/ES/IT/RU/W1; APAC had an extra source-currency
   branch, so a mechanically identical helper call was still unreachable.
5. **For rounding/currency bugs, assert exact amounts, not abs/existence.** The
   fix should prove `Value Entry` ACY equals the document/ARC amount and reconciles
   to G/L; where signs matter, assert signed values.
6. **For application/undo bugs, prove the link, not the message.** Check the item
   application or item-entry relation points to the ILE just posted/reversed. An earlier fix used `ItemJnlPostLine.GetItemLedgerEntryNo()` because the old field held
   the wrong entry number for subcontracting undo.
7. **For extensibility fixes, place the event at the old calculation seam.** The
   publisher must fire after standard filters are set and before `FindSet()`/`CalcSums()`
   if the purpose is to let extensions refine the costing set.

---

## §2 Adjust Cost / average-cost calculation bugs

The corpus is thin on direct `Adjust Cost - Item Entries` product-code defects;
most lived findings are adjacent seams that cost adjustment later consumes.
Treat them as guardrails for the next real adjust-cost bug.

- **Protect the entry-number allocation window, not just the caller:** CU22 `PostSplitJnlLine` allocates ILE and Value Entry numbers and
  later inserts those entries. A `Commit()` inside that window can release locks
  while cached entry numbers are still pending, causing duplicate ILE/Value Entry
  numbers. The fix shape was `CommitBehavior::Ignore` around the split posting
  loop with an opt-out event. The review pushback was about the test: a subscriber
  after insertion does not prove the dangerous window. Put the regression `Commit()` call
  into `OnBeforeInsertItemLedgEntry` or `OnBeforeInsertValueEntry` so the lock/no-
  duplicate invariant is actually tested.
- **Average-cost filter hooks must pass the record by `var`:**
  `OnCalculatePreciseCostAmountsOnAfterFilterOpenInboundItemLedgerEntry` fires
  after `OpenInbndItemLedgEntry` has item/open/positive/location/variant filters
  and before `FindSet()`. Without `var`, subscribers cannot refine open inbound
  ILEs, so the event is functionally useless for average-cost calculation. If the
  next average-cost bug is an extension/filter bug, verify the event sits exactly
  between standard filters and the read.
- **Cost Adjustment / Item Card action duplication is UI-only:** when a bug mentions Cost Adjustment actions, separate UI discoverability
  from valuation logic. An earlier fix only hid base item data actions when Manufacturing
  was enabled and left cost adjustment data processing unchanged. Do not infer an
  adjust-cost engine bug from duplicated Export/Import actions.
- **Re-enable cost-adjustment tests when the product fix lands:** disabled SCM Inventory Costing IV tests covered ARC
  posting and adjustment scenarios. When fixing a costing defect, check whether a
  disabled-test entry exists for the exact costing batch/IV scenario and remove
  only that entry after the underlying source-currency/costing issue is fixed.

---

## §3 Value Entry ACY / rounding / expected-vs-actual bugs

This was the densest valuation cluster. The repeated symptom: document currency
is the Additional Reporting Currency (ARC), but CU22 recalculates Value Entry ACY
from LCY using another exchange rate, so inventory valuation no longer reconciles
with G/L Additional-Currency Amount.

- **Use the document amount only for the real ARC scenario:** the
  special path should run when `ItemJnlLine."Source Currency Code"` equals the
  non-empty Additional Reporting Currency and there are no cost add-ons. The APAC
  copy initially called `ShouldUseDocumentAmountForACY()` only inside
  `Source Currency Code = ''`, making the new branch unreachable for the exact bug
  condition. In localized posting code, prove the predicate is reachable in each
  layer, not just textually present.
- **Cover purchase posting where currency factor differs from posting-date rate:** the minimum test is a purchase posting with document currency =
  ARC and a currency factor different from the posting-date exchange rate. Assert
  the Value Entry ACY amount equals the source document amount and reconciles with
  the G/L Entry Additional-Currency Amount.
- **Expected-cost and actual-cost legs need separate proof:** early
  coverage proved expected and actual direct item costs, but later changes still
  needed branch-specific proof. If `Expected Cost` can be true on receipt and false
  on invoice, assert both legs. Do not assume invoice follows receipt because the
  helper name is shared.
- **Item charges are not automatically part of the direct-item ARC shortcut:** adding `ItemJnlLine."Item Charge No." = ''` narrowed
  `ShouldUseDocumentAmountForACY()`. That was plausible, but the review blocked
  because no item-charge ARC purchase test proved item charges still reconcile.
  Any change to this guard must include a purchase item-charge case where document
  currency = ARC.
- **Do not drop the per-base-unit ACY rounding residual on the actual leg:** the accepted fix added `RoundingResidualAmountInvdACY`, computed as
  invoiced quantity times the per-base-unit ACY unit-cost residual, and used it in
  the invoiced/actual leg: `DirCostACY := "Unit Cost (ACY)" * "Invoiced Quantity"
  + RoundingResidualAmountInvdACY`. This mirrors the expected leg, but scales by
  `"Invoiced Quantity"` instead of `Quantity`. The proving test used a non-base
  unit of measure so the per-base-unit ACY cost rounds and would otherwise drop a
  residual; it asserted both receipt expected and invoice actual Value Entry ACY
  amounts equal the exact document ACY amount.
- **Amount tests must assert exact cost fields, not existence:** for this class, assert `Value Entry."Cost Amount (Expected)
  (ACY)"` and/or `"Cost Amount (Actual) (ACY)"`, and assert the G/L Entry
  Additional-Currency Amount. A `RecordIsNotEmpty(ValueEntry)` assertion would miss
  the whole bug.

---

## §4 Item charges' cost effect

Item charges are valuation entries. They are not just purchase-document metadata.
When a charge is assigned to an item line, the cost effect must land on the right
receipt ILE(s), with the right quantity and amount.

- **Separately invoiced item charges must post a Value Entry:** the root defect was: receive the item line first; later post an item-
  charge invoice with the target item line's `Qty. to Invoice = 0`; no charge
  Value Entry is created, `Qty. Assigned` stays `0`, `Quantity Invoiced` becomes
  `1`, and the purchase order cannot be deleted because
  `TestField("Qty. Assigned", "Quantity Invoiced")` fails. The correct direction
  is to reuse the existing receipt distribution helpers (`PostDistributeItemCharge`
  / `PostItemCharge`) from `Purch.-Post` instead of inventing a parallel value-
  entry writer.
- **Never `FindFirst()` one receipt for an order-line charge:** the
  reviewed fix found `Purch. Rcpt. Line` by `Order No.` + `Order Line No.` and
  posted the full charge against the first receipt. That corrupts cost when the
  order line was received in multiple partial receipts. Loop all matching receipt
  lines and split `Qty. to Assign` / `Amount to Assign` proportionally by each
  receipt's `Quantity (Base)`, mirroring the path where a charge is posted per
  receipt.
- **The item-charge regression needs two invariants:** assert the
  charge Value Entry cost amount and valued quantity, and assert the purchase
  charge line has `Qty. Assigned = Quantity Invoiced`. The original symptom was
  both a missing valuation entry and an assignment-state mismatch.
- **Return/Credit Memo symmetry is a conscious follow-up, not accidental silence:** the new path intentionally targeted `Order`/`Invoice`. The review
  called out that `Return Order`/`Credit Memo` can plausibly suffer the same
  separate-invoice assignment bug. If the next bug is on the return side, resolve
  return-shipment lines and mirror the sign/quantity handling there; do not reuse
  purchase-receipt sign rules blindly.
- **ACY guard changes must include item-charge coverage:** if a CU22
  predicate excludes `"Item Charge No." <> ''`, prove an ARC item-charge purchase
  still posts Value Entry ACY amounts that reconcile with G/L.

---

## §5 Cost application / exact-cost reversing / undo

Application bugs usually look like the wrong entry was chosen, not like no entry
was written. Check the ILE number and application relation before changing amounts.

- **Partial invoicing must keep the Negative Adjmt. ILE eligible until fully
  invoiced:** project consumption through Get Receipt Lines posted the
  second partial invoice's Value Entry to the wrong ILE because the lookup only
  found a Negative Adjmt. ILE with `Invoiced Quantity = 0`. After the first partial
  invoice, that was false even though the entry was not fully invoiced. Use
  `Completely Invoiced = false` for this lookup so later partial invoices continue
  applying to the correct Negative Adjmt. ILE.
- **Undo relation keys must come from the ILE just posted:** in `Undo Posting Management`.`PostItemJnlLineAppliedToList`,
  subcontracting undo filled `TempItemEntryRelation."Item Entry No."` from
  `ItemJnlLine."Item Shpt. Entry No."`. For subcontracting, that value can be a
  capacity ledger entry number, not the reversing output ILE. Use
  `ItemJnlPostLine.GetItemLedgerEntryNo()` from the same global CU22 instance that
  posted the line; guard it to the subcontracting/non-zero scenario so non-
  subcontracting undo stays unchanged. The tests re-enabled a lot-tracking undo
  case because the defect only showed on that sensitive path.
- **Drop-shipment unapply events belong before the application entry read:** `Undo Sales Shipment Line.UnApplyDropShipment` needed an event after
  standard filters on `Item Application Entry` and before `FindFirst()`, so
  extensions using load fields can add extension fields before the record is read
  and later modified/deleted by item application unapply logic. If the next exact-
  cost reversing bug is an extension-field/load-field bug, place the seam there.
- **Message-only undo fixes are not valuation fixes:** a
  better `NoLinesToReverseErr` on empty Sales/Purchase/Transfer undo selections did
  not change posting, application, or valuation state. If a bug is about wrong cost
  reversal, do not stop at the selection/error path.

---

## §6 Revaluation and standard-cost worksheet bugs

The review corpus has little direct revaluation math. The useful lived lessons are
about standard cost and the revaluation entry points that feed Value Entries.

- **`Calculate Inventory Value` / Revaluation Journal are the revaluation entry
  point, but the Value Entry fields prove the fix.** Use report 5899 to populate
  the journal and page 5803 to inspect it, but verify the posted result in Value
  Entry fields `"Partial Revaluation"`, `"Valuation Date"`, and the actual/ACY
  cost fields. Do not claim a revaluation fix from worksheet lines alone.
- **Standard-cost SKU updates must respect the setup/source of SKU costs:** the bug was that single-level capacity/material cost for SKU could be
  calculated/overwritten when Manufacturing Setup says SKU manufacturing costs are
  loaded separately. The final reviewed change was small (widening a message from
  `Text[250]` to `Text`), but the root scenario is the useful rule: standard-cost
  worksheet/report fixes must preserve whether SKU manufacturing costs are loaded
  separately, and long explanatory messages must not fail the run.
- **Manufacturing cost calculation extension points need all overloads:** expected production-order cost had a normal overload and a non-
  inventory-material overload. The first review found the new handled event only
  on one overload. The final fix added a separate `OnBeforeCalcProdOrderLineExpCost`
  shape for the non-inventory-cost path. If a standard/expected-cost bug has two
  calculation overloads, cover both or explicitly prove one cannot run.
- **IT SKU cost events need the item context they actually use:** the
  IT `CalcRtngLineCostSKU` path used `MainItem` to resolve subcontractor prices;
  the W1 path did not. The event surface had to pass `MainItem` only in the IT
  event. For localized standard-cost bugs, do not flatten W1 and IT signatures if
  the localized calculation uses extra cost context.

---

## §7 Inventory valuation and manufacturing cost reports

Report bugs are still costing bugs when they change filters, sums, event seams, or
formatted financial amounts. Treat layouts and navigation as lower risk only when
they demonstrably do not change calculation.

- **Inventory Valuation report 1001 must not depend on CH-only fields:**
  the Excel-layout fixes moved calculation toward Item FlowFields such as `Opening
  Bal. ILE Qty.`, `Increases ILE Qty.`, and `Cost Posted To G/L`, but those fields
  were added only to the CH Item table while W1 report 1001 read them. If a report
  calculation is in W1, the fields/events it reads must exist in W1, not only in a
  localization layer.
- **Preserve `Value Entry` filter events when optimizing report sums:**
  `OnItemOnAfterGetRecordOnAfterValueEntrySetInitialFilters` and
  `OnCalculateItemOnBeforeAssignDecreaseAmounts` let subscribers refine Value
  Entry filters before opening/increase/decrease/G/L sums. Replacing the sums with
  FlowFields bypassed those subscriber changes. Any performance rewrite of
  Inventory Valuation must either keep the old event behavior or add a compatible
  replacement before the sums are calculated.
- **Excel financial layouts need amount/quantity formats:** Inventory
  Valuation's visible Excel pivot tables and sheets cannot leave amount and
  quantity cells as General. Add explicit number formats for LCY amounts and
  quantities so decimal precision/separators do not vary by culture.
- **NA Inventory Valuation report 10139 needs event parity with W1:**
  extensions could compile against W1 report 1001 events but not the NA report.
  The accepted shape added a `SkipItem` event before child ILE processing and a
  `Value Entry` filter event after initial filters and before `CalcSums()`. Default
  behavior must remain unchanged with no subscriber.
- **Inventory Valuation Power BI placement is navigation-only if report objects do
  not change:** moving actions from Finance Manager to Business
  Manager did not alter report pages, setup records, posting, financial
  calculations, permissions, or event contracts. Do not overfit a valuation engine
  fix to a role-center action bug.
- **Cost Shares Breakdown WIP mode must filter before inserting capacity cost rows:** report 5848 already applied Item filters when printing
  WIP buffer rows, but capacity ledger entries for unrelated production items were
  inserted before that filter. Apply the temporary Item + `CopyFilters(Item)` +
  `IsEmpty()` pattern before `InsertCapLedgEntryCostShare()` so an Item filter does
  not show unrelated production orders.
- **Cost-share override events must sit before standard share application:** report 5848 needed an event that lets subscribers replace how cost
  share applies to capacity and overhead amounts. The default path still adds the
  same inventory adjustment order costs, calculates `ShareOfCost` when `OutputQty
  <> 0`, and multiplies the same buffer fields. Additive event, no default behavior
  change.

---

## §8 Recurring agentic-review findings — fix these *before* opening review

These are issues the automated reviews repeatedly caught on costing/valuation changes.
Pre-empting them saves review rounds.

- **A posted Value Entry existing is not enough.** Assert the right ILE, `Valued
  Quantity`, `Invoiced Quantity`, `Cost Amount (Actual/Expected)`, ACY fields, and
  assignment state relevant to the defect. An earlier fix's first test would have
  passed with a wrong amount and wrong receipt distribution.
- **Partial receipts and partial invoices are first-class costing cases.** If the
  fix finds one receipt (`FindFirst()`) or only `Invoiced Quantity = 0`, add a multi-
  receipt or second-partial-invoice test. Earlier fixes are the pattern.
- **Expected and actual cost legs are separate branches.** For receipt+invoice or
  expected-cost posting bugs, assert both `Expected Cost = true` and actual entries
  where the bug can hit both. An earlier fix only closed after the actual leg's residual
  matched the expected leg.
- **ACY fixes require a reconciliation assertion.** When document currency equals
  ARC, assert Value Entry ACY equals the document amount and G/L Additional-
  Currency Amount. A currency factor different from the posting-date rate is what
  exposes the double-conversion bug.
- **Layer copies are not behaviorally identical just because names match.** APAC's
  extra source-currency branch made the new W1-style ACY helper unreachable. Check control flow in every changed layer copy.
- **If a guard excludes item charges, add an item-charge test.** `"Item Charge No."
  = ''` in an ACY helper is a financial branch change, not a harmless narrowing.
- **Event requests must prove the subscriber can change the costing set.** Events
  for filters need a `var` record and must fire after standard filters but before
  `FindSet()`/`FindFirst()`/`CalcSums()`.
- **Report performance rewrites must preserve extension semantics.** Replacing
  Value Entry loops with FlowFields can silently bypass old filter events. Extension parity is part of correctness for valuation reports.
- **Excel layouts for valuation/cost reports need explicit formats.** Financial
  amount and quantity cells/pivots should not be General.
- **Undo/application fixes must assert the relation points to the entry just
  posted or unapplied.** For sensitive undo paths, use the posting codeunit's
  authoritative last ILE number or the filtered Item Application Entry, not a
  nearby shipment/capacity entry field.
- **Costing test re-enablement should be surgical.** Remove disabled-test metadata
  only for fixed ARC posting/adjustment scenarios; leave unrelated still-failing
  costing batch tests disabled until their underlying defect is fixed.
