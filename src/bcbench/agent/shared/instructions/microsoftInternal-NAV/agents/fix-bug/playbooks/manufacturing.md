# Manufacturing Bug-Fix Playbook (Business Central)
> **How to use this guide — read first.** This is a playbook of practical hints, not a source of indisputable truth. Don't spend time confirming or refuting the statements here, and don't go looking for a pull request, work item, commit, author, or date behind any recommendation. Use it as a helper — apply what fits the bug in front of you, and use your own judgment for the specifics.

> Domain knowledge for the automated bug-fix agent working on **Manufacturing
> (non-subcontracting)** bugs in this repo's base-app layers: production orders, routings, production BOMs,
> components, capacity, consumption/output, flushing, production journals,
> planning worksheet / MRP, and Assembly only where it overlaps manufacturing
> copy or availability behavior.
>
> The Manufacturing app folder is a shell; the code covered here lives in the
> base-app layer under `src/Layers/W1/BaseApp/Manufacturing/`.
>
> This is **not** an AL language guide. It only carries manufacturing-specific
> knowledge and the concrete lessons — what worked and what didn't — from past
> fixes. Generic AL rules, generic CI hygiene, and anything the compiler,
> publisher, or analyzer rulesets catch on their own are deliberately left out.
>
> **Subcontracting is excluded.** If the bug is about subcontracting purchase
> orders, WIP transfer orders to subcontractors, subcontractor pricing, or the
> legacy IT/W1 app migration seam, switch to the separate Subcontracting playbook.
> This file only cross-references overlap where a production-order/routing fact is
> reusable.

---

## §0 The area in one picture

Manufacturing is a chain of **definitions → planning → orders → journals/posting
→ ledgers/reports**. Most bugs in this corpus were not "math is hard" bugs; they
were bugs where one link in that chain used a narrower key, stale filter, or
wrong unit than its sibling path.

1. **Definitions** — `Production BOM Header` / `Production BOM Line` /
   `Production BOM Version`, plus `Routing Header` / `Routing Line` /
   `Routing Version`. Certification gates bad combinations before they become
   production-order refresh failures.
2. **Planning** — MRP / planning worksheet reads Item and SKU production BOMs,
   routing cost, low-level codes, and requisition lines. SKU-level BOMs are real
   manufacturing setup, not an afterthought.
3. **Production orders** — orders move through Simulated / Planned / Firm Planned
   / Released / Finished. Lines carry item/BOM/routing; components carry material
   demand; routing lines create capacity needs and capacity ledger entries.
4. **Posting** — consumption and output post through item journals / production
   journals into Item Ledger, Value Entry, and Capacity Ledger. The WIP reports
   read those posted entries and can be financially wrong even when posting was
   correct.
5. **Capacity display** — Work/Machine Center calendars, load pages, Power BI, and
   Capacity Ledger visuals all convert from capacity-unit codes to time factors.
   A display-only bug can still hide or blank the real capacity picture.

### Key objects you will keep meeting (current IDs)

IDs below are current in this repo at playbook creation time. Prefer these
names over stale object IDs from bug text.

| Object | Type | Current ID | Area | Notes |
|---|---:|---:|---|---|
| `Manufacturing Setup` | table/page | **99000765 / 99000768** | Setup | Order no. series, SKU cost loading, capacity UOM, flushing defaults, no-output finishing. |
| `Production Order` | table | **5405** | Orders | Header status/source; statuses use enum 5405. |
| `Production Order Status` | enum | **5405** | Orders | Simulated, Planned, Firm Planned, Released, Finished. |
| `Prod. Order Line` | table | **5406** | Orders | Item line; carries `Production BOM No.`, `Routing No.`, `Finished Qty. (Base)`, `Scrap %`. |
| `Prod. Order Component` | table | **5407** | Components | Material demand; key filters include Status, Prod. Order No., Prod. Order Line No. |
| `Prod. Order Routing Line` | table | **5409** | Routing/capacity | Operation demand; Previous/Next Operation No. matter for parallel routing. |
| `Prod. Order Capacity Need` | table/page | **5410 / 99000820** | Capacity | Planned operation capacity demand. |
| `Production BOM Header` | table | **99000771** | BOM | Header status and version no. series. |
| `Production BOM Line` | table | **99000772** | BOM/components | Version Code + Line No. filtering is easy to get wrong. |
| `Production BOM Version` | table/page | **99000779 / 99000809** | BOM versions | Certification must validate version lines too. |
| `BOM Status` | enum | **99000771** | BOM | Used by header/version certification gates. |
| `Routing Header` | table | **99000763** | Routing | Has Type Serial/Parallel and version no. series. |
| `Routing Line` | table | **99000764** | Routing | Has Standard Task Code and operation sequencing. |
| `Routing Version` | table/page | **99000786 / 99000810** | Routing versions | Version-line pages mirror routing-line page behavior. |
| `Work Center` | table/card/list | **99000754 / 99000754 / 99000755** | Capacity | Parent for machine centers; has calendars/load. |
| `Machine Center` | table/card/list | **99000758 / 99000760 / 99000761** | Capacity | Capacity unit often resolves through parent work center. |
| `Calendar Entry` | table | **99000757** | Capacity | Keyed by Capacity Type + No. + Date for "available until" style checks. |
| `Capacity Ledger Entry` | table | **5832** | Posting/capacity | Posted output/capacity cost source for WIP and Power BI. |
| `Capacity Unit of Measure` | table | **99000780** | Capacity | `Code` is not the same as `Type`; this caused Power BI blanks. |
| `Item Journal Line` | table | **83** | Posting | Consumption/output journal line carrier. |
| `Flushing Method` | enum | **5417** | Posting/flushing | Manual, Forward, Backward, Pick+ variants. |
| `Consumption Journal` | page | **99000846** | Posting | Manual component consumption entry. |
| `Output Journal` | page | **99000823** | Posting | Manual output/capacity posting entry. |
| `Production Journal` | page/codeunit | **5510 / 5510** | Posting | Combined consumption/output UI path. |
| `Requisition Line` | table | **246** | Planning | Planning worksheet/carry-out line. |
| `Planning Worksheet` | page | **99000852** | Planning/MRP | Carries action messages into orders. |
| `Planning Component` | table/list | **99000829 / 99000861** | Planning/MRP | Component demand before order creation. |
| `Stockkeeping Unit` | table/card | **5700 / 5700** | Planning/cost | SKU-level `Production BOM No.` and cost loading are separate paths. |
| `Calculate Low-Level Code` | codeunit | **99000793** | Planning/MRP | Must traverse Item and SKU BOM links. |
| `Mfg. Carry Out Action` | codeunit | **99000818** | Planning/MRP | Creates prod. orders from requisition/planning lines. |
| `Calculate Standard Cost` | codeunit | **5812** | Costing | SKU and non-inventory material paths differ. |
| `Mfg. Cost Calculation Mgt.` | codeunit | **99000758** | Costing | Routing/cost-time/expected-cost calculations. |
| `Copy Production Order Document` | report | **99003802** | Orders | Request-page lookup can keep stale filters. |
| `Inventory Valuation - WIP` | report | **5802** | WIP reporting | Production Order - WIP financial report. |
| `Inventory Valuation - WIP CZA` | report | **31133** | WIP reporting | CZ sibling with same stale-value trap. |
| `Calculate Work Center Calendar` | report | **99001046** | Capacity | Card action / request filter path. |
| `Calc. Machine Center Calendar` | report | **99001045** | Capacity | Card action / request filter path. |
| `Standard Cost Worksheet` | table/page | **5841 / 5841** | Costing | Single-level material/capacity cost calculations. |
| `Assembly Header` / `Assembly Line` | tables | **900 / 901** | Assembly overlap | Assemble-to-order copy path only. |
| `Assemble-to-Order Link` | table | **904** | Assembly overlap | Link that must survive sales-quote copy. |

### Reliable manufacturing markers / fields

- **Always filter production-order children by line when the child is line-scoped.**
  `Prod. Order Component` and `Prod. Order Routing Line` bugs commonly appear when
  code uses only Status + Prod. Order No. and accidentally crosses production
  lines. An earlier WIP fix read the `Prod. Order Line` with
  `Finished Qty. (Base) = 0`; a related subcontracting fix hit the same
  `Prod. Order Line No.` trap.
- **Do not confuse capacity UOM `Code` with capacity UOM `Type`.** Manufacturing
  Setup stores `Show Capacity In` as a code, while Power BI time factors are keyed
  by type. Custom codes like `TIMER` must resolve through `Capacity Unit of
  Measure.Type`.
- **SKU-level production definitions are first-class.** A valid SKU can carry a
  `Production BOM No.` even when the Item path is blank or different. Low-level
  code, standard cost, and planning must include SKU loops and permissions.
- **Routing line descriptions are operation data, not just work-center names.** If
  a requisition/planning path is sourced from a `Prod. Order Routing Line`, prefer
  the operation descriptions where the line/work center matches; only fall back to
  the work center for the documented blank/mismatch cases.
- **Parallel routing is real UI state.** Previous/Next Operation No. are hidden for
  Serial but must be visible on Routing and Routing Version lines when the header
  Type is Parallel.

---

## §1 The loop that worked

1. **Identify the manufacturing link where the bug lives.** Definitions,
   planning, order creation, journal posting, capacity display, and WIP reporting
   each have different keys. Do not fix a report symptom by changing posting until
   you have proven posting is wrong.
2. **Find the sibling path that already behaves correctly and mirror its filter.**
   Event availability from Item Card/Requisition Line already cleared the date
   filter; production-order line/component actions needed the same behavior. Sales/Purchase/Assembly copy-document reports already excluded the
   current document; production order copy needed the same lookup pattern plus
   stale-filter cleanup.
3. **Check W1 and localized copies before declaring a fix complete.** The WIP
   stale-consumption reset had to be applied to W1 report 5802 and CZA report
   31133. Routing-description logic was correctly applied identically
   to W1 and IT copies.
4. **For setup-driven defaults, preserve precedence.** New defaults belong in
   Manufacturing Setup only when the document/header has no explicit value; never
   backfill existing headers silently.
5. **Follow review rounds to final state.** An earlier fix looked acceptable until a
   later round found a missing `Stockkeeping Unit` read permission; final accept
   came only after the permission matched the new SKU traversal. The
   production code was acceptable, but test rewrites temporarily removed negative
   no-series and print assertions before most were restored.

---

## §2 Production orders and order documents

- **Self-copy belongs in the lookup, not as a late error.** `Copy Production Order
  Document` showed the current order when source status equaled target status, so
  users could select it and only fail later. Exclude the target `No.` in the lookup
  like Sales/Purchase/Assembly/Inventory copy-document patterns — and clear that
  filter when the source status changes, or a stale `No.` filter can hide a valid
  order in another status.
- **Released production orders from planning are not just a new enum label.** The
  carry-out flow must set status through `SetProdOrderStatus`, use the released
  order no. series, include released orders in the print filter, and run forward
  flushing after line/component creation. Tests that only prove the report handler
  fired are weak; prove the released order reaches the print dataset.
- **No-series negative cases matter for planning carry-out.** An earlier change briefly
  removed the released-order no-series regression; review asked to restore it
  because a missing released no. series should fail before creating orders.
- **Production Order - WIP vs embedded Power BI WIP are different user surfaces.**
  Renaming the embedded page caption to `Production Order WIP (Power BI)` fixed a
  Tell Me ambiguity without changing the page object name or AL references. If a bug is search/discoverability, do not touch report 5802.

---

## §3 Routings, routing versions, and standard tasks

- **Parallel routing fields must be controlled by the parent routing type.** The
  line subpages need a Boolean from the parent Routing/Routing Version page so
  `Previous Operation No.` and `Next Operation No.` show for Parallel and stay
  hidden for Serial. This is page-state logic; table data was not the problem.
- **Routing and Routing Version pages must be tested separately.** An earlier fix changed
  both normal routing lines and routing version lines; the review blocked until
  TestPage coverage could assert visibility for both Serial and Parallel.
- **Validating `Routing Line.Standard Task Code` copies more than a code.** It
  deletes/inserts Routing Tool, Routing Personnel, Routing Quality Measure, and
  Routing Comment Line records from Standard Task relations. Demo-data or repair
  helpers that validate the field need permissions for both routing relation
  tables and standard-task relation tables.
- **Rerunnable demo-data fixes must update existing routing lines.** An earlier fix first
  inserted Standard Tasks but returned early when a routing line already existed,
  leaving upgraded/rerun companies with blank Standard Task Code. The accepted fix
  backfilled blank existing lines, temporarily reopened certified routings,
  preserved descriptions, and then restored status.
- **Do not overrule documented operation mappings.** In an earlier fix, review questioned omitted Standard Task Codes for later parallel/subcontracting demo
  operations; the author documented that those operations were outside the mapping,
  and the suggestion was treated as disputed rather than blocking. For the next
  bug, match the reported operation map, not every visually similar operation.
- **Routing description preservation has an intentional asymmetry.** In the
  requisition-line update path, routing `Description` is copied even when blank;
  routing `Description 2` falls back to work center `Name 2` when blank. Tests
  were added that lock in that asymmetry. If a later agent "normalizes" both
  fields, it may reintroduce the reported bug.

---

## §4 Production BOMs, BOM versions, and components

- **Certification checks must include Production BOM Versions, not just headers.**
  A variant-mandatory item on a Production BOM Version line with blank Variant Code
  must block certification before status is persisted. Scope the line loop to the
  current Version Code, run before Modify/Commit, and mirror the header validation
  pattern.
- **Event context should match the header event shape.** An earlier fix added
  `OnBeforeCheckVariantIfMandatory`; the review asked to pass the old version
  record by value because it is context only and should match the same event on
  `Production BOM Header`.
- **Production BOM Comment Line relations must filter by Version Code.** The old
  relation let a `BOM Line No.` from a different version validate. Tightening the
  TableRelation is a data-integrity fix, but remember it can reject legacy comment
  rows that only existed because the relation was buggy.
- **SKU-level BOMs must participate in low-level-code traversal.** The planning
  worksheet needing a second regenerative run was caused by Calculate Low-Level
  Code ignoring Production BOMs stored on SKUs. Add both upward and downward SKU
  traversal, deduplicate multiple SKUs that point at the same BOM, and persist the
  recalculated item low-level code from SKU `Production BOM No.` validation.
- **A missing SKU BOM path may be unreachable for domain reasons.** Review
  initially flagged passing a blank BOM record to `SetRecursiveLevelsOnBOM`; that concern was
  withdrawn because SKU `Production BOM No.` is table-relation validated and the
  existing `Status = Certified` guard prevents writes. Before "fixing" a scary
  branch, compare sibling procedures and validation gates.
- **Planning Component is a separate pre-order table.** If a BOM/component bug only
  appears before carry-out, look for `Planning Component` propagation as well as
  `Prod. Order Component`. The subcontracting playbook has the analogous field-
  propagation trap; for non-subcontracting, use it as a reminder to enumerate all
  BOM → planning → production-order transfer paths.

---

## §5 Capacity, work centers, machine centers, calendars, and Power BI

- **Calendar-entry "available until" FlowFields key on capacity type and center no.**
  Work Center and Machine Center fields should filter `Calendar Entry` by matching
  `Capacity Type` + `No.` and use the key that includes Date so MAX(Date) returns
  the latest calendar date. This made stale calendars visible before scheduling
  fails.
- **Card actions must pass a narrowed table view to the existing calendar reports.**
  Work Center Card runs report 99001046 filtered by current `No.`; Machine Center
  Card runs report 99001045 filtered by current `No.`. Request pages expose Work
  Center Group Code for work centers and Work Center No. for machine centers.
- **Capacity display conversion is not a persistence change, but it can break public
  page procedures.** An earlier fix added `Capacity Shown In` to Work/Machine Center
  calendar/load pages. The old 3-parameter `Load` / `SetLines` overloads must stay
  compatibility wrappers; they should not suddenly read Manufacturing Setup,
  convert values, or `TestField("Show Capacity In")` for existing extension callers.
- **Load % is not a capacity quantity.** Conversion tests needed to
  prove Work Center and Machine Center values are scaled by TimeFactor while Load %
  stays unchanged.
- **Machine Center conversion may need the parent Work Center.** the accepted
  direction resolved the capacity unit through the parent Work Center for Machine
  Center display. Do not assume the machine center alone carries all conversion
  context.
- **Power BI measures must use capacity UOM type, not setup code.** An earlier fix corrected
  blanks when Manufacturing Setup `Show Capacity In` was a custom code like
  `TIMER` by joining `Manufacturing Setup - PBI API` to `Capacity Unit of Measure`
  and exposing `code` + `type`; all 21 measures across Work Center, Machine Center,
  Capacity Ledger Entries, Prod Order Capacity Need, and Production Orders then
  lookup time factors by type.
- **Power BI setup joins should degrade gracefully.** Review warned
  that an inner dataitem join can hide the whole manufacturing setup row if `Show
  Capacity In` is blank or points at a missing capacity UOM. Prefer a left-outer
  shape when the visible setup row is still meaningful.

---

## §6 Consumption, output, WIP, finished-without-output, and scrap

- **Report variables that describe one Value Entry must be reset for every Value
  Entry, including non-WIP rows.** Report 5802 reused stale `ValueOfMatConsump`
  after a consumption entry when a non-WIP value entry followed, making reported
  material consumption differ from Value Entries. Move resets before the WIP check;
  apply the same pattern to CZA report 31133.
- **Do not reset production-order accumulators just because one variable was stale.**
  In an earlier fix, `ValueOfRevalCostAct` and `ValueOfRevalCostPstd` were *not* the same
  per-record reset problem; they accumulate for the production order and are used
  by `ValueEntryOnPostDataItem`. Resetting them per value entry would change the
  calculation.
- **Finished without output is a legitimate Manufacturing Setup scenario.** Report
  5802 had to move WIP cleared by finishing a production order without output into
  an Expensed WIP column and remove it from ending WIP, Consumption, and Capacity
  columns. Detection must be per production order line with `Finished Qty. (Base) =
  0`, not just per order header.
- **Capacity cost must follow no-output reclassification too.** An earlier fix first
  handled material, but review found capacity still counted in both Capacity and
  Expensed WIP. The accepted fix added capacity to `OrderExpensedCap` and
  subtracted it from `ValueOfCapSum` / `TotalValueOfCap`.
- **Mixed orders are the dangerous test shape.** A production order with one line
  that has output and one line finished without output catches order-level WIP
  detection mistakes. An earlier fix added this mixed-order test after review.
- **The corpus is thin on scrap-specific bugs.** The reliable lived lesson is that
  scrap affects both material and routing/capacity calculations through the same
  manufacturing cost functions; when changing scrap behavior, look at the
  production-order line, component, and routing/capacity paths together. No
  standalone scrap fix in this corpus established a more specific rule.

---

## §7 Flushing and production journals

- **Forward flushing after planning carry-out must happen after line/component
  creation.** The released-order carry-out path kept tests that assert the
  component is consumed; if you create released orders directly and forget the
  forward-flush timing, the order exists but material is not consumed.
- **Released & Print is still a production-order creation path.** Do not fork a
  print-only path that skips flushing or status/no-series logic. The final
  shape kept one status mapping and one carry-out production-order creation flow,
  then verified print inclusion separately.
- **Production Journal / Output Journal / Consumption Journal have little direct
  corpus coverage.** For the next bug in these pages, derive behavior from the
  posted ledger/report symptom: earlier fixes prove report 5802 can be
  wrong even when the journal posting flow is correct. Do not change journal
  posting to fix a report-only stale-variable bug.

---

## §8 Planning worksheet, MRP, SKU cost, and standard cost

- **Event availability from production orders must clear the inherited due-date
  filter.** Opening Item Availability by Event from prod. order lines/components
  inherited `Item."Date Filter" = 0D..Due Date`, hiding demand after the production
  order Due Date. Clear the date filter like the Period view and requisition-line
  Event path; cover both line and component actions.
- **Planning worksheet low-level codes must see SKU-only multi-level BOM chains.**
  The one-run MRP result depends on Calculate Low-Level Code assigning 0/1/2 levels
  through SKU Production BOMs; otherwise a second regenerative run is needed before
  dependent component supply appears.
- **New table reads in planning code need object permissions.** An earlier fix added SKU
  traversal but initially missed `TableData "Stockkeeping Unit" = r` on the
  codeunit. The fix was one line, but without it users could hit a runtime
  permission error exactly in the fixed scenario.
- **SKU manufacturing cost loading is opt-in setup.** In Standard Cost Worksheet,
  do not overwrite SKU costs when Manufacturing Setup says SKU manufacturing costs
  are loaded separately. The visible review finding was only a message
  `Text[250]` overflow, but the domain scenario was the SKU/material/capacity cost
  split.
- **Manufacturing cost events must cover both inventory and non-inventory material
  cost paths.** Handled events were added for SKU routing cost, direct unit
  cost, cost-time inputs, and expected production-order costs. The first round
  missed the overload with `ExpNonInvMatCost`; the accepted fix added
  `OnBeforeCalcProdOrderLineExpCostWithNonInvMatCost`.
- **IT and W1 cost paths can need different context.** A localized path had to pass
  `MainItem` through the IT `OnCalcRtngCostSKUOnBeforeCalcRtngLineCostSKU` event
  because that IT SKU route uses `MainItem` to resolve subcontractor prices. W1 did
  not need the parameter because its overload does not take it. This is a
  cross-reference only; if the bug is actually subcontractor-price calculation,
  use the Subcontracting playbook.

---

## §9 Manufacturing setup, versions, demo data, and Assembly overlap

- **Manufacturing version defaults are optional and non-backfilling.** An earlier fix
  added Manufacturing Setup defaults for production BOM version and routing version
  number series. New headers inherit only when their own version series is blank;
  explicit header values win; blank setup preserves old behavior; existing headers
  are not backfilled.
- **Production definition wizard and Contoso data are setup consumers.** An earlier fix
  covered wizard-created headers and Contoso PV10/RV10 generation. If a setup
  default changes header insert logic, update helper setup order so common/finance
  setup exists before manufacturing setup seeds version numbers.
- **Produced-item demo data belongs in the Manufacturing module.** An earlier fix added a
  `PRODUCED` item template through demo-data codeunit 5310 before manufactured
  items are created. It reused the existing helper with a new overload and kept the
  old signature unchanged.
- **Demo-data overloads must preserve old callers.** The final round called
  out that the old `InsertItemTemplateData` signature stayed unchanged, while the
  manufacturing overload supplied planning/manufacturing fields. Follow that
  pattern for future demo-data additions.
- **Assembly overlap is copy-document permission/link preservation, not production
  posting.** earlier fixes corrected Team Member copying of sales quotes with
  assemble-to-order links by granting narrow inherent permissions on the copy paths
  that read/recreate `Assembly Header`, `Assembly Line`, and
  `Assemble-to-Order Link`. The tests had to include resource components,
  item-component ATO, and archived quote copy.
- **Resource-only Assembly tests are not enough.** The first round used a
  resource-only BOM; review asked for item-component ATO because availability and
  component reads are the typical path. The later rounds added it and were accepted.

---

## Recurring agentic-review findings — fix these before proposing a change

- **Compatibility wrappers must remain compatibility wrappers.** If you add a new
  overload for capacity display, demo data, or manufacturing setup defaults, keep
  the old public signature behavior unchanged. The capacity-display change remained blocked because
  old `Load` / `SetLines` overloads started reading setup and converting values;
  the demo-data change was accepted after keeping the original demo-data overload intact.
- **Clear filters you add to request pages/lookups.** An earlier fix added a self-document
  exclusion filter but review caught that changing status could leave a stale `No.`
  filter. If a request page can be reused after a field change, remove the old
  filter in the else path.
- **When you add a new table read to a codeunit, update its permissions.** SKU reads
  in `Calculate Low-Level Code` needed `TableData "Stockkeeping Unit" = r`. Standard Task validation copied routing-relation rows and needed those
  relation-table permissions.
- **Apply fixes to localized sibling objects with the same caption/logic.** WIP
  stale-value fixes needed W1 report 5802 and CZA report 31133. Routing
  description fixes needed W1 and IT copies. Capacity calendar actions
  touched W1, IT, and CZ areas.
- **Tests must hit the branch you changed, not just the headline scenario.** An earlier fix changed line and component availability but initially tested only the line;
  another changed two routing pages and needed UI tests for both; the API
  test already created the custom-code capacity UOM but did not assert the new
  `type` column.
- **Do not weaken tests while aligning a change.** An earlier change briefly removed negative
  no-series coverage, print-dataset verification, and `AssertEmpty` in a
  multi-order test. Most were restored after review; print still had a weaker
  assertion.
- **Use the net change diff when reviewing later rounds.** the later
  review explicitly checked that the test-only delta was in the net change diff before
  treating removed assertions as authored changes. Avoid treating base-branch churn as authored changes.
- **For display conversions, test the unchanged values too.** Capacity quantities
  should scale by TimeFactor, but Load % should not. Power BI visible
  text changing from code to type must be confirmed, not assumed.
- **A data-integrity TableRelation fix can expose old bad data.** The BOM
  Comment Line relation tightening was correct, but the review still called out
  that legacy rows created under the buggy relation may fail revalidation.
- **For no-output/finished-order bugs, include mixed production lines.** Order-level
  tests can pass while line-level WIP is wrong. An earlier fix needed a mixed output /
  no-output order to prove the per-line logic.
- **Assembly copy fixes need resource, item-component, and archive variants.** The fix was only accepted after item-component and archived quote scenarios were
  covered; the later fix started with resource + item-component coverage.

