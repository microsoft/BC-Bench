# Warehouse / Inventory / Item Tracking Bug-Fix Playbook (BC / NAV)

> **How to use this guide — read first.** This is a playbook of practical hints, not a source of indisputable truth. Don't spend time confirming or refuting the statements here, and don't go looking for a pull request, work item, commit, author, or date behind any recommendation. Use it as a helper — apply what fits the bug in front of you, and use your own judgment for the specifics.

> Domain knowledge for the automated bug-fix agent working on **Warehouse /
> Inventory / Item Tracking** bugs in this repo's W1/base-app layers: warehouse receipts/shipments,
> put-away/pick (directed + basic), bins and bin content, warehouse
> activities/worksheets, inventory movements/reclass/transfers, item
> availability, and serial/lot/package tracking with reservations.
>
> This is **not** an AL language guide. It carries only warehouse/tracking
> knowledge and concrete lessons — what worked and what did not — from past
> fixes and reviews. Inventory costing/valuation and manufacturing-internal math
> are deliberately out of scope, except where warehouse handling touches them.

---

## 0. The area in one picture

The same item quantity can be represented in **three overlapping models** before it finally becomes a posted ledger fact:

1. **Warehouse handling** — source documents create `Warehouse Request` rows, then worksheet/activity/document lines (`Pick`,
  `Put-away`, `Movement`, `Invt. Pick`, `Invt. Put-away`, warehouse receipt/shipment) move quantities between bins and staging
  bins.
2. **Inventory / transfer application** — item journals, transfer orders, and source posting create/apply `Item Ledger Entry`
  rows. Transfers have outbound, in-transit, and inbound faces; inbound reservation and application are not the same as outbound
  availability.
3. **Tracking and reservations** — `Tracking Specification` carries proposed serial/lot/package assignment; `Reservation Entry`
  carries availability, source, and paired-reservation state. Warehouse pick lines can reserve or consume tracked stock before
  anything is posted.

**Fix the seam the bug lives on.** A lot of defects were not in the main posting routine but in the glue: source references copied
to warehouse requests, pick worksheet availability excluding the wrong bins, temporary availability entries for unregistered
picks, or tracking status copied as a real reservation when it was only a prospect.

### One-step vs. two-step handling

- **Basic warehouse / inventory documents** use inventory picks, inventory put-aways, and movements directly from source/inventory
  needs. They often have bins but not directed put-away and pick.
- **Advanced / directed warehouse** uses warehouse receipts/shipments plus warehouse put-aways/picks. Location fields (`Require
  Receive`, `Require Shipment`, `Require Put-away`, `Require Pick`, `Directed Put-away and Pick`) decide which documents are
  legal.
- **Staging bins are not pickable stock.** Receipt bins and shipment bins are handling bins; pick worksheet and availability logic
  must not offer their stock as ordinary available-to-take quantity.
- **FEFO changes bin choice.** In basic warehouse movements with `Pick According to FEFO`, a blank `From Bin` can be meaningful:
  the engine chooses the lot/bin. Do not widen a FEFO-specific blank-bin fix to all movements.

### Tracking model in one paragraph

`Tracking Specification` (table 336) is the document-line working copy. `Reservation Entry` (table 337) is the
availability/reservation fact and is keyed by source fields plus serial/lot/package values. A copied tracking line is often
`Reservation Status::Prospect`; forcing `Reservation` without the paired entry corrupts the model. Warehouse
activity lines also carry serial/lot/package values and can represent allocated but unregistered demand; item tracking
availability must subtract them or the same lot/package can be chosen twice.

### Key objects you will keep meeting (current IDs)

IDs below are current for this area.

| Object | Type | Current ID | Area | Notes |
|---|---|---:|---|---|
| `Location` | table | **14** | Inventory / Warehouse | Warehouse setup fields: `Require Pick`, `Require Shipment`, `Bin Mandatory`, `Directed Put-away and Pick`, `Pick According to FEFO`, receipt/shipment bins. |
| `Item Ledger Entry` | table | **32** | Inventory | Final posted inventory facts; transfer application must honor selected tracking. |
| `Tracking Specification` | table | **336** | Tracking | Working tracking lines; includes `Source Type`, `Source Subtype`, `Source ID`, `Source Ref. No.`, serial/lot/package fields. |
| `Reservation Entry` | table | **337** | Reservation | Real reservation/prospect rows; wrong status/source/quantity creates orphan or missing entries. |
| `Reservation Entries` | page | **497** | Reservation | Inspection page for table 337. |
| `Reservation` | page | **498** | Reservation | User-facing reservation flow; inbound transfer errors live here. |
| `Available - Transfer Lines` | page | **99000896** | Transfer / Reservation | Separate transfer availability page; do not assume `Reservation` page tests cover it. |
| `Available - Item Ledg. Entries` | page | **504** | Inventory | Selects open ILE application candidates. |
| `Item Tracking Lines` | page | **6510** | Tracking | Main tracking assignment page. |
| `Item Tracking Summary` | page | **6500** | Tracking | Lot/serial/package availability summary fed by codeunit 6501. |
| `Item Tracking Management` | codeunit | **6500** | Tracking | `CopyItemTracking`/tracking-copy status traps. |
| `Item Tracking Data Collection` | codeunit | **6501** | Availability / Tracking | Builds tracking availability; must account for unregistered picks. |
| `Transfer Header` | table | **5740** | Transfer | `Direct Transfer`, `In-Transit Code`; do not validate direct transfer false after route setup unless intended. |
| `Transfer Line` | table | **5741** | Transfer | Source type for transfer reservation/application; use `Database::"Transfer Line"`, not magic `5741`. |
| `Warehouse Request` | table | **5765** | Warehouse source | Source key rows; upgrade/rename source fields only under exact filters. |
| `Warehouse Activity Header` | table | **5766** | Activity | Stores header flags such as `Do Not Fill Qty. to Handle`. |
| `Warehouse Activity Line` | table | **5767** | Activity | Pick/put-away/movement lines; has Activity Type, Action Type, bin, source, tracking, quantity fields. |
| `Warehouse Pick` | page | **5779** | Activity | Advanced pick document. |
| `Warehouse Put-away` | page | **5770** | Activity | Advanced put-away document. |
| `Inventory Pick` | page | **7377** | Activity | Basic pick; `Activity Type = Invt. Pick` matters. |
| `Inventory Put-away` | page | **7375** | Activity | Basic put-away. |
| `Warehouse Movement` | page | **7315** | Activity | Movement activity page. |
| `Warehouse Receipt Header` / `Line` | tables | **7316 / 7317** | Document | Two-step receipt document. |
| `Warehouse Shipment Header` / `Line` | tables | **7320 / 7321** | Document | Two-step shipment document; posted/picked quantities affect availability. |
| `Warehouse Entry` | table | **7312** | Warehouse ledger | Bin quantities, cubage, weight, posted warehouse movements. |
| `Bin Content` | table | **7302** | Bins | Quantity, pick qty, ATO component pick qty, `Block Movement`; keyed by location/bin/item/variant/UOM. |
| `Bin Type` | table | **7303** | Bins | Flags `Receive`, `Ship`, `Pick`; directed locations use these for staging/pickability. |
| `Bin` | table | **7354** | Bins | `Bin Type Code`, capacity/ranking fields. |
| `Whse. Worksheet Line` | table | **7326** | Worksheet | Movement/pick/put-away worksheet rows; template creation bug in an earlier fix. |
| `Whse. Worksheet Name` / `Template` | tables | **7327 / 7328** | Worksheet setup | Template `Page ID` must honor custom caller page. |
| `Pick Worksheet` / `Movement Worksheet` / `Put-away Worksheet` | pages | **7345 / 7351 / 7352** | Worksheet | Worksheet UI over table 7326. |
| `Create Pick` | codeunit / report | **7312 / 5754** | Pick creation | Codeunit creates picks; report drives request/print flow. |
| `Create Inventory Pick/Movement` | codeunit | **7322** | Basic whse | Inventory pick/movement creation, FEFO movement, job availability aggregation. |
| `Warehouse Availability Mgt.` | codeunit | **7314** | Availability | Pick worksheet / shipment-bin availability calculations. |
| `WMS Management` | codeunit | **7302** | Validation | Shared warehouse journal validation including bin-content movement checks. |
| `Whse.-Activity-Post` | codeunit | **7324** | Posting/register | Inventory pick/warehouse activity posting checks. |
| `Whse. Jnl.-Register Line` | codeunit | **7301** | Warehouse journal | Registers warehouse journal lines; cubage/weight must be set before run. |
| `Whse.-Source - Create Document` | report | **7305** | Put-away / movement creation | Internal put-away event trap. |
| `Phys. Invt. Order-Post` | codeunit | **5884** | Physical inventory | Posting should mirror warehouse/transfer link-copy placement. |
| `Inventory Profile Offsetting` | codeunit | **99000854** | Planning / reservation | Requisition base-quantity rounding affects reservation cleanup. |
| `Matched Order Line Mgmt.` | codeunit | **5826** | Receipt matching | Receipt-to-order filters; only adjacent to this playbook, but useful analogy. |

### Reliable markers and fields

- Use `Location` setup to decide document legality: `Require Receive`, `Require Shipment`, `Require Put-away`, `Require Pick`,
  `Bin Mandatory`, and `Directed Put-away and Pick`. Directed destinations usually should **not** receive a transfer-to bin from
  custom workflow setup.
- Use `Bin Type.Receive/Ship/Pick`, not only `Location."Shipment Bin Code"`, when reasoning about directed staging bins. Multiple
  Ship-type bins exist in real warehouses.
- Treat `Warehouse Activity Line."Activity Type"` values `Pick` and `Invt. Pick` separately. A blank `Action Type` does not turn
  an inventory pick into a normal warehouse pick.
- Preserve the source key as a set: `Source Type`, `Source Subtype`, `Source ID`, `Source Batch Name`, `Source Prod. Order Line`,
  `Source Ref. No.`. Partial migration of warehouse source references can corrupt availability or navigation.
- For transfer reservation direction, `Transfer Line` source subtype distinguishes outbound vs inbound; inbound quantities are not
  reservable before receipt and must get an inbound-specific message.
- For tracking copies, `Prospect` is usually the right status when copying item tracking without creating the matching reservation
  pair. `Reservation` status requires paired positive/negative entries.
- For transfer application, serial/lot/package values selected on the transfer entry must participate in the open-ILE filter
  before the candidate entry is picked.

---

## 1. The loop that worked

1. **Classify the location first.** Basic bin-mandatory, directed put-away and pick, and no-bin locations have different valid
  bin/document flows. Many fixes are just "apply this bin only for bin-mandatory non-directed locations".
2. **Find the sibling path and mirror it.** Non-FEFO already filtered Pick bins where FEFO did not; transfer-from bin
  validation already had the guard that transfer-to needed; warehouse/transfer posting already showed where to copy
  record links.
3. **Follow source references end to end.** A source-type fix must cover creation, item tracking, availability helpers, Show
  Source Document, and upgrade rows that carry old keys.
4. **Separate "availability shown" from "posting/application done."** Unregistered picks, receipt bins, shipment bins, and
  in-transit transfer lines affect what should be selectable long before ledger posting.
5. **When tracking is involved, test the exact tracked value that survives.** It is not enough that a document is created; assert
  the selected lot/package/serial stayed on the purchase/transfer/pick line or consumed the right ILE.
6. **For multi-round bugs, carry reviewer objections forward until the final resolution.** Several good fixes had a correct first
  idea but an unsafe scope or a weak test that only later got fixed.

---

## 2. Receipts, shipments, and staging bins

Symptoms: pick creation says "nothing to handle", pick worksheet overstates stock, serial/lot appendices mix between posted
shipments, or document posting loses header metadata.

- **Ship-type bins are not pick bins:** a directed location with multiple Ship-type bins failed a second pick because
  previous picked quantity sat in a non-default Ship bin. The fix had two parts: add the Pick-only bin type filter to the FEFO
  branch in `Create Pick`, and change `Warehouse Availability Mgt.` to sum **all** Ship-type bins in `CalcQtyOnShipmentBins`, not
  only `Location."Shipment Bin Code"`. Guard the default-bin fallback so the default shipment bin is not double-counted when it
  already has a Ship bin type. The useful test assertion was not just quantity; it asserted the new Take line's `Bin Code` was the
  pick bin, not the ship bin.
- **Pick worksheet availability must exclude receive and shipment handling stock:**
  `CalcQtyAvailToTakeOnWhseWorksheetLine` needed to ignore current receipt and shipment bins, and to cap bin-content availability
  for receive / put-away locations so received-not-put-away quantity stays unavailable even if the receipt bin code changes later.
  The remaining review gap was the symmetric shipment-bin-lineage case: if the shipment bin code changes after a pick is
  registered, picked-not-shipped quantity in the old shipment bin must still stay unavailable.
- **Batch-printed posted shipment tracking appendix is a layout-scope bug until proven otherwise:** the GB
  `SalesShipment.rdlc` fix removed a tablix-level `<BreakLocation>Start</BreakLocation>` from the Serial/Lot Number appendix.
  Because the symptom was lot rows appearing under the wrong document, review required manual verification with **at least two**
  posted shipments in one batch and confirmation that the appendix is scoped under the outer per- document group
  (`No_SalesShptHeader` + `OutputNo`). Pagination-only changes are not obviously enough when the symptom is cross-document mixing.
- **Record links on posted physical inventory should mirror posting flows:** `Phys. Invt. Order-Post` had to call
  `RecordLinkManagement.CopyLinks` immediately after inserting the posted Phys. Invt. Order Header and each posted recording
  header. The acceptable placement matched Sales, Purchase, Warehouse Receipt/Shipment, Transfer, Inventory Document, and
  Assembly: copy inside the standard `if not IsHandled then` insert block, so subscribers that replace the insert own link copying
  too.

---

## 3. Pick / put-away / activity and worksheet bugs

Symptoms: wrong quantity to handle, wrong source bin, worksheet rows that do not clear, custom worksheet pages opening with the
wrong template, or event subscribers receiving a stale warehouse record.

- **Create Pick request flags must reach the header:** the Pick Worksheet path already put `Do Not Fill Qty. to Handle`
  into `CreatePickParameters`, and line creation already used it to clear line qty. The missing piece was copying that flag onto
  `Warehouse Activity Header` before insert, so registration can still see the user's request. Because the shared `Create Pick`
  codeunit also serves Warehouse Shipment, Movement Worksheet, Internal Pick, Production, Assembly, and Job paths, keep the change
  at the central parameter-to-header point and test the Pick Worksheet path that lost it.
- **FEFO pick reshuffle must consume picked quantity per lot, not per reservation row:** warehouse pick registration
  for nonspecific reservations first tried to keep reservation quantity per lot, but with two reservation entries for the same lot
  it subtracted the full picked quantity from each entry. The final fix used a per-lot remaining-quantity dictionary: calculate
  picked quantity once per lot, then decrease the remaining amount as each `Reservation Entry` is processed. The regression
  created the same lot through two item ledger entries, registered the FEFO pick, posted shipment, and proved the other orders
  could still pick/ship.
- **Internal put-away after quality inspection must source current bin content, not stale receive bin:** after a WHITE
  receipt is put away, a failed- quantity internal put-away cannot use the original receive bin. The resolver should use positive
  `Bin Content` for non-tracked inventory at bin-mandatory locations, excluding receive/adjustment bins, while item-tracked
  inventory keeps using `GetCurrentLocationOfTrackedInventory`. If multiple bins qualify, allocate the requested
  Specific/Sample/Failed/Passed quantity **once across bins** and error on shortfall; do not copy the full quantity to every bin.
  The accepted test asserted no line sourced from RECEIVE and total put-away quantity equaled the failed quantity.
- **Inventory Pick for ATO: skip ATO per line, not for the whole document:**
  `Whse.-Activity-Post.CheckQuantityInBinContentForTracking` needed to skip activity lines marked `Assemble to Order`, because
  assembly output bin content is created later by `Sales-Post`. A first-line document-level exit was unsafe: if the ATO line was
  first, normal tracked lines skipped validation too. Remove the header/first-line exit and rely on the per-line ATO check; test a
  mixed pick with the ATO line first.
- **Bin replenishment + FEFO blank `From Bin` needs two narrow fixes:** in codeunit 7322, when FEFO leaves worksheet
  `From Bin` blank, availability must not count the destination bin's earliest lot because it cannot move onto itself; and the
  handled-line buffer must be recorded under blank `From Bin` so it matches and clears the worksheet row. The final fix gated
  destination-bin exclusion on `CurrLocation."Pick According to FEFO"` and only used the blank-bin buffer behavior for FEFO blank
  inventory movements. The test reproduced earliest lot split between source and destination, then asserted full movement and
  worksheet cleanup.
- **Warehouse worksheet template creation must persist the caller's page:** table 7326 `TemplateSelection` filtered by
  the caller's `PageID` but, on first-time template creation, stored the standard page ID. The fix is to validate `"Page ID"` with
  the input page in the zero-template path. Because this writes setup data, the scenario-specific regression should start with no
  `Whse. Worksheet Template`, call `TemplateSelection(PageTemplate = Movement, custom PageID)`, assert the stored page ID, then
  call again and prove no duplicate/failure. If similar warehouse journal/bin-creation template routines keep the old pattern,
  state whether scope is intentional.
- **Report 7305 internal put-away event must expose the actual line:** `Whse.-Source - Create Document` raised
  `OnBeforeProcessWhseMovWkshLines` inside the `Whse. Internal Put-away Line` dataitem but passed the sibling `Whse. Put-away
  Worksheet Line`, which was stale and the wrong record type. The correct event is a dedicated
  `OnAfterWhseInternalPutAwayLineOnPreDataItem` at the end of that `OnPreDataItem`, after filters are set. Be careful removing the
  old event: even a bad event may have subscribers; keep or explicitly assess it.

---

## 4. Bins, bin content, capacity, and movement blocking

Symptoms: blocked bins can still be depleted, capacity is bypassed by split movements, or workflow-created transfers carry invalid
bin codes.

- **`Bin Content.Block Movement` must be enforced on every outbound posting path that posts warehouse journal lines:** negative adjustments from bin-mandatory non-directed locations must check the `From Bin Code` bin content for
  `Outbound` or `All`; sales shipment posting must call `WMS Management.CheckWhseJnlLine` before `WhseJnlPostLine.Run`. The lookup
  must include Location, From Bin, Item, Variant, and Unit of Measure. Review also called out purchase return shipment as the
  sibling outbound path to check; if it is in scope, add the same validation there. Add an inbound control scenario so `Block
  Movement = Outbound` still allows positive inbound movement.
- **Capacity checks need cubage/weight on the posted warehouse entry:** `Prohibit More Than Max. Cap.` could be
  bypassed by splitting Inventory Movement lines because the first partial registration posted a warehouse entry without
  Cubage/Weight; the next capacity calculation did not see the occupied capacity. Fill cubage and weight on the warehouse journal
  line with existing `WMSMgt.CalcCubageAndWeight` before `WhseJnlRegisterLine.Run`. The final test used
  `WarehouseActivityLine.SplitLine`, registered the first split part, then verified the second split part was blocked.
- **Quality transfer destination bins are only valid for bin-mandatory non-directed destinations:**
  the workflow bin flows from `QltyWorkflowResponse.GetWellKnownKeyBin` into the disposition buffer `"New Bin Code"`, then into
  `Transfer Line."Transfer-To Bin Code"`. Apply it under a non-empty guard **and** a destination-location guard mirroring the
  transfer-from side: destination is `Bin Mandatory` and not `Directed Put-away and Pick`. If the destination changes to a non-bin
  or directed location, clear the persisted workflow bin, not only the page variable. Cover switching an already-configured
  non-directed destination to a directed one.
- **Do not accidentally turn a routed transfer into a direct transfer:** for quality transfer dispositions, a
  direct transfer is derived from an empty in-transit location. When an in-transit code has already been validated onto the
  header, do not call `Validate("Direct Transfer", false)` just because the computed flag is false; leave the default false and
  route intact. Only validate `Direct Transfer` when the disposition is actually direct.
- **Localized demo in-transit codes need one source of truth:** Inventory and Warehousing Contoso setup created
  duplicate Italian own-logistics in-transit locations (`LOG PROP.` vs `LOG. PROP.`) because two translatable labels represented
  the same logical code. Warehousing now uses `Create Location.OwnLogLocation` instead of a separate label. This is a forward
  fix only; existing duplicates are not cleaned up.

---

## 5. Transfers, reclass, and inventory document seams

Symptoms: inbound transfer reservation gives a false "fully reserved", transfer receipt applies against the wrong lot/package, or
planning/drop-shipment flows create/delete bad reservation rows.

- **Inbound transfer lines are not reservable before receipt:** the user-facing bug was a non-direct transfer shipped
  but not received; reserving the inbound line showed generic `Fully reserved.` although no inbound reservation existed. Both
  `Reservation.Page.al` and `AvailableTransferLines` need the inbound-specific message. Do not gate that message on `Qty. in
  Transit (Base) <> 0`; unshipped inbound lines need the same clear explanation. If you add an Available Transfer Lines filter,
  test the **page** (`SetSourceTableFilters`), not a direct `Transfer Line` table filter.
- **Use `Database::"Transfer Line"` and transfer direction, not raw source type numbers:** `5741` is table `Transfer
  Line`, but raw literals made the reservation guard harder to review across rounds. This is one of the rare readability findings
  worth carrying in the playbook because source-type mistakes change reservation behavior.
- **Transfer application must filter by selected tracking:** when a transfer receipt applies open item ledger entries,
  the selected serial/lot and package values on the posted transfer entry must be marked as required before the open-entry search
  applies tracking filters. The package behavior was added through the existing package extension subscriber before the existing
  package filter hook ran. Tests verified the unselected first lot/package kept remaining quantity while the selected second
  lot/package was consumed.
- **Transfer demand planning extensibility must protect the current profile:** an event before transfer demand
  inventory profile creation is valid for split demand (cut-length) scenarios, but if the handled event receives the same
  `SupplyInvtProfile` record that later continues through the procedure, a subscriber can leave the current record on the wrong
  inserted profile. Save and restore the current profile or pass a copy when `IsHandled` can insert multiple transfer demand
  profiles.
- **Project / job warehouse source references must align with direct reservation source references:** direct Job
  Planning Line reservations used table 1003 / subtype Order while warehouse picks used `Database::Job` / subtype 0, causing
  reservation availability to be double-counted or mis-keyed. The final fix changed warehouse activity, worksheet, request,
  item-tracking, and creation paths to use Job Planning Line consistently, kept Show Source Document opening the Job Card, and
  made `Create Inventory Pick/Movement.GetSourceLineNo` return `-1` for both `Database::Job` and `Database::"Job Planning Line"`
  so multiple reserved planning lines still aggregate.
- **Warehouse Request upgrade code must filter before renaming key fields:** because `Warehouse Request` source fields
  are key fields, migration used rename/delete-insert style logic. A round regressed by removing `Source Type = Database::Job` and
  `Source Subtype = 0` filters before `FindSet`, which could rename Sales, Purchase, Transfer, or other requests to Job Planning
  Line. Always add a non-job control row to upgrade tests.
- **Requisition-line base quantity rounding can orphan reservations:** when planning project demand to a
  purchase order with a non-base purchase UoM, the purchase quantity rounds and recalculates base quantity. If `Inventory Profile
  Offsetting` copies a slightly different `Quantity (Base)` than `SupplyInventoryProfile."Remaining Quantity (Base)"`, later
  deletion leaves reservation entries and blocks deleting the project planning line. The fix used a UoM-scaled tolerance (`Qty.
  per Unit of Measure`, not one fixed precision step) and then aligned base fields with the demand. The deterministic test used
  Qty. per UoM = 12 and asserted no reservation entries remained.

---

## 6. Item tracking / reservation interplay

Symptoms: lots look available while already on picks, purchase-order creation corrupts table 337, Description lookup skips
auto-reservation, or drop shipment tracking is deleted as an illegal field change.

- **Unregistered picks consume tracked availability:** `Item Tracking Data Collection` must add temporary demand for
  outstanding warehouse pick and inventory pick lines with matching item, variant, location, serial/lot/package, positive
  outstanding quantity, and a different source. Round 5 caught that the code comment claimed inventory picks were covered but the
  filter still only had `Activity Type = Pick`; include `Invt. Pick` too. Later rounds added source- reservation netting so split
  Take lines do not subtract the same source-line reservation more than once. This is the key pattern for "available lot" bugs:
  group by source + tracking, skip the current source, subtract matching source reservation once, then insert only the remaining
  temporary demand.
- **Nonspecific reservation reshuffle must preserve tracking truth:** for FEFO warehouse picks, deleting surplus
  reservations and keeping picked lots must account for split reservation entries on the same lot. Use remaining qty per lot;
  never recompute the full picked qty independently for each reservation row.
- **Copied tracking from planning should usually be `Prospect`, not `Reservation`:** `CopyItemTracking3` with
  `Reservation Status::Reservation` created only one side of a pair, then later code looked for the missing counterpart and raised
  `Reservation Entry does not exist`, leaving table 337 corrupted after Order Planning / Create Purchase Orders. Reverting to
  Prospect status fixed the data model. If removing a public overload that accepted a status parameter, obsolete it first and
  document that the status is ignored until the clean tag.
- **Do not delete the old serial-tracking test without replacing the scenario:** the removed test had encoded
  the broken Reservation status, but it still represented the original bug scenario. Replace it with an end-to-end Order Planning test that
  creates/cancels purchase orders for a lot/serial-tracked item and proves reservation entries remain valid and the flow can
  re-run.
- **Sales Description lookup must capture `No.` changes before `SaveRecord`:** for `Reserve = Always` items selected
  through Description lookup, `CurrPage.SaveRecord` resynced `xRec`, so `Rec."No." <> xRec."No."` became false and
  `AutoReserve` was skipped. Capture `NoHasChanged` before save, return a `SelectionRestored` flag from
  `RestoreLookupSelectionWithResult`, and use both in the auto-reserve guard. The accepted dispute: setting `CurrFieldNo` to
  `FieldNo("No.")` was safe because `CheckWarehouse` is skipped on the restore path and item availability / credit checks are
  `Type = Item` guarded.
- **Single-instance lookup state must be cleared before the forced-error point:** the negative test became meaningful
  only when it asserted `Lookup State Manager.IsRecordSaved` true before the error and false after. The state is in-memory and
  non-transactional, so `asserterror` rollback does not clear it; production must clear it in `RestoreLookupSelectionWithResult`
  before `OnBeforeNoOnAfterValidate` fires.
- **Drop-shipment purchase creation with lot tracking must preserve both sales link and lot reservation:** Req.
  Line-Reserve was treating valid drop-shipment fields (`Sales Order No.`, `Sales Order Line No.`, `Sell-to Customer No.`) as
  illegal reservation changes and deleting tracking before PO creation. The fix is narrow, but the test must assert more than
  "purchase line exists": set a location, verify the drop-shipment sales link survives, and verify expected lot
  reservation/tracking survives.
- **Project planning line deletion bugs are reservation bugs too:** if a bug ends as "cannot delete source
  line," inspect whether a planning or document conversion step created reservation entries with base qty not matching the source
  demand. The correct assertion is often "no reservation entries remain" after deleting the downstream order and source line.

---

## 7. Availability-specific traps

Symptoms: an availability page hides future demand, availability overstates stock in staging bins, or warehouse availability
changes after source-key migration.

- **Clear date filters when opening Item Availability by Event from production lines/components:** the Event view from
  production order lines was capped at `0D..Due Date`, hiding later demand that Period view and Item Card showed. Clear
  `Item."Date Filter"` before `ShowItemAvailabilityByEvent`, matching the Period path and the requisition-line Event path. If
  changing both line and component actions, cover both; the original review accepted with a request to test the component branch
  too.
- **Pick worksheet availability and Create Pick availability must agree:** if one path excludes Ship/Receive
  bins and the other path counts them, users get either false pickability or "nothing to handle." When fixing one calculation,
  trace the sibling calculation (`Create Pick`, `Warehouse Availability Mgt.`, worksheet line calc) for the same bin-type rule.
- **Source-line aggregation can be semantically meaningful:** changing job warehouse source type from Job to Job
  Planning Line was correct for reservations, but availability calculation would have changed if `GetSourceLineNo` started
  filtering one planning line at a time. Returning `-1` kept the old aggregate behavior for multiple reserved job planning lines.
- **Transfer inbound availability is not reservation permission:** a line can appear in a transfer availability page
  and still be non-reservable from the inbound side until receipt. Keep page filtering, validation, and error messages aligned,
  and do not let a table-filter-only test stand in for the page behavior.

---

## 8. Recurring agentic-review findings — fix these *before* submitting changes

These are the warehouse/tracking-specific issues reviewers repeatedly caught. Pre-empting them saves rounds.

- **A test helper must not raise the production error itself.** An earlier fix initially had `AutoReserveTransferLine` throw
  `InboundReservationErr` in the test helper, so the test passed without executing the `Reservation` page / Reservation Management
  guard. Let the page/codeunit raise the error.
- **Tests must drive the UI/page object when the bug is in page filters.** An earlier fix kept a test that filtered `Transfer Line`
  directly while the production behavior was `AvailableTransferLines.SetSourceTableFilters`.
- **Line-order exits are dangerous in mixed warehouse activity documents.** An earlier fix needed a per-line ATO skip; a first-line ATO
  exit would skip validation for normal tracked lines if the ATO line sorted first.
- **Quantity allocation across multiple bins must sum to the requested quantity.** An earlier fix first risked giving the full
  failed/specific quantity to each eligible bin. Allocate remaining quantity per bin and fail on shortfall.
- **FEFO-specific fixes need FEFO guards.** An earlier fix originally applied a destination-bin exclusion to any blank-`From Bin`
  inventory movement; the final fix gated it on `Pick According to FEFO`.
- **When changing source-key models, include upgrade controls for unrelated rows.** An earlier fix regressed by renaming unfiltered
  `Warehouse Request` rows; the final test seeded a non-job Sales Header request and verified it stayed unchanged.
- **When changing reservation quantities, test split entries for the same lot.** An earlier fix only became safe after testing a lot
  split across two item ledger / reservation entries.
- **When fixing availability around picks, include both `Pick` and `Invt. Pick`.** An earlier fix missed inventory picks even though the
  comment claimed blank action type covered them.
- **When adding handled events around mutable records, protect the current record.** An earlier fix exposed `SupplyInvtProfile` by var
  before continuing the standard planning flow; a handled subscriber that inserts several profiles can leave the caller on the
  wrong record unless you save/restore or pass a copy.
- **When applying a workflow bin, mirror both directions.** An earlier fix's transfer-to bin needed the same location guard shape as
  the existing transfer-from bin.
- **When clearing invalid bin setup in a page, persist the clear.** An earlier fix's important behavior was clearing the stored
  workflow argument, not just hiding or blanking the on-screen variable.
- **When fixing report tracking appendices, verify cross-document scope manually.** An earlier fix could not reasonably add an RDLC
  rendering test, so the right evidence was a batch print with at least two tracked shipments.
- **When copy-item-tracking status changes, preserve compatibility and prove both old and new bugs.** An earlier fix needed an
  obsolete wrapper for the removed public overload and a replacement test for the older serial-tracking scenario.
- **When using location helper setup in tests, assert the warehouse fact, not just that a document exists.** Examples: pick Take
  line `Bin Code` is the pick bin, transfer line `Transfer-To Bin Code` is set/cleared correctly,
  lot/package remaining quantity changes on the selected value only, and no reservation entries remain after deletion.

---
