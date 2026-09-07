# Subscription Billing Bug-Fix Playbook (BC / NAV)

> **How to use this guide — read first.** This is a playbook of practical hints, not a source of indisputable truth. Don't spend time confirming or refuting the statements here, and don't go looking for a pull request, work item, commit, author, or date behind any recommendation. Use it as a helper — apply what fits the bug in front of you, and use your own judgment for the specifics.

> Domain knowledge for the automated bug-fix agent working on **Subscription
> Billing** bugs in `this repo` (W1 `Subscription Billing` app:
> subscription contracts, service objects/commitments, recurring billing,
> usage-based billing, billing proposals/lines, contract deferrals, price
> updates, renewal and termination).
>
> This is **not** an AL language guide. It only carries Subscription
> Billing-specific knowledge and the concrete lessons — what worked and what
> didn't — from past fixes. Generic AL rules and anything the compiler,
> publisher/deployment, analyzer rules, or permission-set checks will flag on
> their own are deliberately left out.

---

## 0. The area in one picture

Subscription Billing is one W1 app, but most bugs sit on the seam between two
record generations:

1. **Source/subscription generation** — the commercial state the user owns:
   `Subscription Header`, `Subscription Line`, customer/vendor subscription
   contracts and contract lines, service-object data, renewal/termination dates,
   price-update templates, and usage-data imports.
2. **Generated billing/posting generation** — temporary or transactional state
   produced from the source: `Billing Line`, `Usage Data Billing`, sales and
   purchase documents, deferral schedules, posted-document extension fields,
   overdue/analysis rows, and renewal quote buffers.

**Decide which generation a bug is in before touching code.** A large share of
fixes were not "the amount formula is wrong"; they were "path X copied the
source value and path Y didn't", "the generated row was filtered differently",
"a page buffer overwrote the user's pending value", or "a cached/generated
answer leaked into the next line/document".

### Key objects you will keep meeting (current IDs)

IDs below are current in repo-relative `src/Apps/W1/Subscription Billing/App`.
The app owns object range **8000..8113** (`app.json`). Verify less-common objects.

| Object | Type | Current ID | App area | Notes |
|---|---|---:|---|---|
| `Subscription Header` | table | **8057** | Service Objects | Source service-object header. |
| `Subscription Line` | table | **8059** | Service Commitments | Source commitment line: dates, price, quantity, discounts, billing base period, renewal/termination fields. |
| `Sales Subscription Line` | table | **8068** | Sales Service Commitments | Sales-document-side commitment line; BOM explosion and FCY bugs land here. |
| `Customer Subscription Contract` | table | **8052** | Customer Contracts | Customer contract header copied into sales billing documents. |
| `Cust. Sub. Contract Line` | table | **8062** | Customer Contracts | Customer contract line linked back to `Subscription Line`. |
| `Vendor Subscription Contract` | table | **8063** | Vendor Contracts | Vendor contract header; mirror sales fixes here when applicable. |
| `Vend. Sub. Contract Line` | table | **8065** | Vendor Contracts | Vendor-side contract line linked back to `Subscription Line`. |
| `Billing Line` | table | **8061** | Billing | Generated billing candidate; holds net amounts and source links. |
| `Billing Line Archive` | table | **8064** | Billing | Billing history; existence matters even when amount is zero. |
| `Billing Proposal` | codeunit | **8062** | Billing | Builds billing lines and calculates billing periods. |
| `Create Billing Documents` | codeunit | **8060** | Billing | Creates sales/purchase invoices/credit memos from billing lines. |
| `Billing Template` | table | **8060** | Billing | Automation/error context; interactive errors need record identity. |
| `Contract Billing Err. Log` | table | **8022** | Billing | Non-interactive/automated billing errors land here. |
| `Usage Data Billing` | table | **8006** | Usage Based Billing | Generated usage-billing rows; `Processing Status` is a correctness boundary. |
| `Usage Data Import` | table | **8013** | Usage Based Billing | Import header; status updates must stay scoped to one import. |
| `Create Usage Data Billing` | codeunit | **8023** | Usage Based Billing | Creates usage billing candidates. |
| `Process Usage Data Billing` | codeunit | **8026** | Usage Based Billing | Updates subscription quantity/price/cost from usage data. |
| `Usage Based Billing Mgmt.` | codeunit | **8029** | Usage Based Billing | Helper surface for connector and billing flows. |
| `Usage Based Pricing` | enum | **8007** | Usage Based Billing | Extensible boundary; `None` is the exclusion, not the upper bound. |
| `Processing Status` | enum | **8012** | Usage Based Billing | `Error` lines must not be processed or reset by unrelated imports. |
| `Price Update Template` | table | **8003** | Contract Price Update | Stores filters for price-update proposals. |
| `Contract Renewal Selection` | page | **8006** | Contract Renewal | Temporary-buffer page for renewal terms. |
| `Sub. Contr. Renewal Subcribers` | codeunit | **8001** | Contract Renewal | Sales-post subscribers; renewal detection can be expensive and cached. |
| `Contract Deferrals Release` | report | **8051** | Deferrals | Releases contract deferral schedules to G/L. |
| `Cust. Sub. Contract Deferral` | table | **8066** | Deferrals | Customer deferral schedule. |
| `Vend. Sub. Contract Deferral` | table | **8072** | Deferrals | Vendor deferral schedule; keep customer/vendor logic symmetric. |
| `Assign Service Commitments` | page | **8065** | Service Commitments | Dialog opened from subscriptions or sales lines; caption context matters. |
| `Extend Contract` | page | **8002** | Customer Contracts | Page parameter setters are the integration seam. |
| `Sales Line` | tableextension | **8054** | Sales Service Commitments | Holds subscription fields and `IsLineAttachedToBillingLine()`. |
| `Purchase Line` | tableextension | **8065** | Sales Service Commitments | Purchase mirror of billing-line attachment checks. |

### Reliable Subscription Billing markers and seams

- A sales/purchase line being "owned by billing" is represented through
  `IsLineAttachedToBillingLine()` / the billing-line link, not by a generic item
  or document-type guess. On `Sales Line`, that helper has caching history — make
  the public result key-aware before exposing or reusing it.
- `Billing Line` amounts are net/VAT-exclusive. If the generated document has
  `Prices Including VAT = true`, convert before assigning document line prices,
  and do it in **all four** paths: sales, purchase, usage-sales, usage-purchase.
- `Usage Data Billing`.`Processing Status = Error` is a hard exclusion. Do not
  process it, do not flip it back to OK through a broad status reset, and do not
  let one import clean another import's errors.
- `Usage Based Pricing` is extensible. `None` is the lower boundary to exclude;
  an upper bounded enum filter silently rejects partner values above the current
  last base enum value.
- Billed/archived state is about **record existence**, not amount totals. A
  zero-value archived billing line is still billing and can lock date edits.
- Renewal and extend-contract pages use temporary buffers. Page refresh triggers
  can reload persistent `Subscription Line` and wipe pending user edits unless
  the current buffered row is read first.

---

## 1. The loop that worked

1. **Read the bug context and identify the exact path.** Subscription
   Billing usually has parallel customer/vendor, sales/purchase, standard/usage,
   per-contract/per-customer, and page/API/import paths. The bug is often one
   missing sibling path, not the shared helper.
2. **Find the mirror path and compare it line-for-line.** Good fixes mirror the
   already-correct sibling: customer deferral → vendor deferral,
   sales document header → purchase document header, standard billing
   price assignment → usage-based billing price assignment.
3. **Keep generated-state filters scoped to the source row/import/document.** If
   you touch status updates, billing-line links, or renewal caches, key them by
   the stable source identity and clear them at document/import boundaries.
4. **When widening extensibility, prove the new surface is deterministic.** A
   public helper with hidden cache requirements or an extensible enum with no
   runtime branch is worse than no API.
5. **For amount fixes, trace source → billing line → document line → posted/deferral
   release.** The same visible invoice amount can be set in standard billing,
   usage billing, deferral release, or renewal quote calculation; cover the one
   the bug actually reaches.

---

## 2. Billing proposals and billing document creation

- **Non-progress billing-period loop:** `BillingProposal.CalculateBillingPeriod`
  could recalculate the same `BillingPeriodEnd` forever when a harmonized customer
  contract's `Next Billing To` capped the period before the requested billing
  date. Fix: keep the previous end date and only loop while the recalculation
  actually moves forward. The capped billing line should still be created and
  advance the subscription from that line.
- **Large-run performance is not just keys:** scale
  fixes touched proposal creation, document creation, usage-data links, progress
  tracking, field loading, transaction checkpoints, and cached reads. Review kept rejecting broad
  speedups without functional proof because billing amounts, document links,
  usage-data links, and extension-visible pricing events are financial behavior.
  If you optimize this area, prove customer and vendor documents, usage lines,
  links, and new transaction-checkpoint semantics.
- **Do not bypass pricing/UoM hooks silently:** the `Billing Price Calc.
  Skip` idea set handled on sales/purchase price, cost, and UoM events while
  billing lines were initialized. That can bypass subscriber adjustments to
  price, cost, quantity, or UoM. Add an opt-out/integration point or prove the
  supported billing result stays identical.
- **New transaction checkpoints change rollback semantics:**
  adding a transaction checkpoint after each created billing document can intentionally preserve earlier
  documents and billing-line updates after a later failure. Treat that as a
  behavior change; test at least two documents where the second fails and assert
  the first is intentionally preserved.
- **No-GUI/Job Queue is a separate billing path:** dialog/progress
  changes must run under `GuiAllowed = false` and still create documents or log
  errors. Do not validate only the interactive page path.
- **External Document No. has two sales-header paths:** per-contract
  billing uses `CreateSalesHeaderFromContract`, where `TransferFields(CustomerContract,
  false)` copies the new field and a subsequent `Validate("External Document No.")`
  retriggers base validation. Per-customer grouped billing uses
  `CreateSalesHeaderForCustomerNo`, where the contract must be looked up and the
  value validated explicitly. If you add contract-header fields, cover both paths.
- **Payment discount belongs to the contract terms:** recurring
  invoices were inheriting the customer/vendor payment discount instead of the
  contract's payment terms. The sales side needed a temporary reassignment because
  W1 `Sales Header` validation checks `xRec`; the purchase side only needed a
  re-validate after `Document Date` was set. Run the recalculation after document
  date validation and assert terms code, discount %, and discount date.
- **VAT-inclusive document prices require gross-up:** billing lines
  store net values. When `Sales Header` / `Purchase Header`.`Prices Including VAT`
  is true, gross up with VAT % and round to Currency `Unit-Amount Rounding
  Precision` before assigning line price. Apply to standard and usage-based sales
  and purchase paths; skip Full VAT. Usage-based VAT-inclusive coverage was the
  review gap.
- **Interactive errors must raise populated `ErrorInfo`:**
  `CreateBillingDocuments` already built error identity for Billing Template and
  Billing Line failures but discarded it by calling `Error(ErrorText)`. Interactive
  paths should raise the populated `ErrorInfo` so the client can navigate to the
  record. Automated billing keeps logging to `Contract Billing Err. Log`. Cover
  both `DisplayOrLogErrorFromBillingTemplate` and `DisplayOrLogErrorFromBillingLine`.
- **Configurable billing-period text is contract-type data:** the
  Billing Period Description belongs on the subscription contract type and should
  reuse the existing Field Translation pattern. Blank values stay on the standard
  label path; when billing creates sales/purchase document lines, resolve text
  using the contract type from the billing contract.
- **Day/week periods do not snap to month end:** explicit
  `Subscription Line End Date` invoice amounts were wrong because day/week
  formulas were treated like month rhythms. For `D` and `W` date formulas, use the
  plain period end; keep month/quarter/year month-end alignment. Include leap-year
  and month-end cases.

---

## 3. Service commitments, sales lines, and assignment flows

- **Assign dialog must know whether it was opened from a sales line:**
  page **8065** `Assign Service Commitments` uses the sales line number and
  description in `DataCaptionExpression = GetCaption()` only when
  `OpenedFromSalesLine` is true; the subscription-header path falls back to the
  package code. Do not make a caption fix that breaks the subscription-header
  dialog.
- **BOM explosion prompt belongs after the component line exists:**
  the correct event order is `Sales-Explode BOM`.`OnExplodeBOMCompLinesOnAfterAssignType`
  before `No.` validation and `OnExplodeBOMCompLinesOnAfterToSalesLineInsert`
  immediately after `Insert()`. Record the component line before `No.` validation,
  skip the early validation path only for that line, clear state after insert,
  then create subscription lines from the inserted sales line with quantity.
- **Foreign-currency BOM explosion must use the cached sales line date:**
  a BOM component creating a `Sales Subscription Line` for an FCY customer failed
  when `GetDate()` hard-read the sales line before it was safely persisted. Use
  the same cached Sales Line helper as the other calculations; keep the FCY
  exchange-rate formula and unit-amount rounding unchanged, and leave `Get()` as
  the normal persisted-line fallback.
- **`IsLineAttachedToBillingLine()` cannot expose a stale Sales Line cache:**
  Purchase Line was a direct lookup and safe. Sales Line returned a cached Boolean
  until `InitCachedVar()` ran, so an external caller reusing one record variable
  across lines could get the previous line's result. The accepted fix stored the
  line identity (`Document Type`, `Document No.`, `Line No.`) with the cached
  value and refreshed when the key changed.
- **Start-date enforcement belongs on the `Subscription Line` field:** page-only checks let imports, APIs, and code paths bypass the
  rule. Validate in the table before `UpdateNextBillingDate`, read the persisted
  line to know whether the old `Next Billing Date` was still the old start date,
  block current billing lines and archived billing-line **existence** (including
  zero amount), allow valid correction/unbilled cases, and exempt temporary
  renewal buffers.
- **Temporary records are legitimate in this app:**
  renewal and selection pages stage changes before applying them. A table-level
  guard must explicitly leave temporary buffers usable; a page refresh must prefer
  the buffer row over reloading the persistent subscription line.

---

## 4. Usage-based billing and connector extensibility

- **Exclude `Processing Status = Error` everywhere in processing:**
  lines rejected for a currency mismatch must not update subscription quantity,
  price, or cost. The robust pattern also changes `SetProcessedUsageDataBillingToOk`
  so it rebuilt filters from the `Usage Data Import` entry number and excluded
  error rows itself instead of trusting a filtered record passed by the caller.
- **Status reset is scoped by import:** a helper that marks processed
  rows OK must be limited to the current import. Do not clear errored lines from
  unrelated imports, and keep its filter shape aligned with the main processing
  loop.
- **Open-ended usage-pricing filters are the extensibility pattern:**
  `SetUsageDataBillingFilters` should include partner `Usage Based Pricing` enum
  values above `Unit Cost Surcharge` while still excluding `None`. The accepted
  proof used a test-only enum value at ordinal 100 and verified exactly one row:
  the extension value was included, `None` was excluded.
- **Expose connector helpers without changing their semantics:**
  custom Usage Data Connector apps need to call the same helper procedures used by
  the generic connector path, especially around `Usage Data Processing.CreateBillingData`.
  The safe change only removes `internal` from existing procedures; it did
  not change filters, metadata creation, amount calculation, event timing, or
  status handling.
- **Usage-based VAT follows the same gross-up rule as standard billing:**
  if the fix touches `SetInvoicePriceFromUsageDataBilling` overloads, add direct
  VAT-inclusive usage tests. Standard billing tests do not prove the usage path is
  reached.

---

## 5. Contract deferrals, G/L routing, dimensions, and price updates

- **G/L Account contract lines use the selected line account:** without deferrals, `CustomerDeferralsMngmt` and
  `VendorDeferralsMngmt` should early-exit so BaseApp's selected `Sales Line."No."`
  / `Purchase Line."No."` remains the posting account. With deferrals, store the
  selected account on the deferral and have `ContractDeferralsRelease` prefer it;
  blank values on existing deferrals and non-G/L lines fall back to General
  Posting Setup.
- **GPS validation must respect deferral-owned accounts:**
  `CheckGenPostingSetup` should not demand a setup contract account when the
  deferral row already carries its own G/L account. This is what lets a G/L
  Account contract line post even when the generic customer/vendor subscription
  contract account is blank.
- **Credit memo reversal is a separate G/L-account proof:** earlier review
  called out missing explicit tests for credit memos
  reversing G/L Account contract lines, with and without deferrals. If you change
  deferral account routing, cover the reversal path.
- **Vendor single-period deferrals mirror the already-correct customer logic:** when the billing period stays inside one calendar month, vendor
  deferrals must use the exact schedule length before falling through to partial
  month or full-month branches. Multi-period schedules keep first/middle/last
  period rules. The existing `OnBeforeInsertVendorContractDeferral` override point
  still fires after calculated values are set.
- **Default Dimension Priorities must survive the Subscription Line merge:** resolve dimensions through the priority-aware path (`Source Code
  Setup` + Dimension Management helpers) like BaseApp Sales/Purchase lines. Keep
  `Subscription Line`.`OnAfterGetCombinedDimensionSetID(Rec)` firing immediately
  after the combined dimension set is computed, or extensions lose the old hook.
  End-to-end proof is a generated invoice line carrying the highest-priority Item
  dimension.
- **Price Update Template filters are user input:**
  a past bug was that proposal default filters overwrote `Price Update Template`
  filters on Subscription Lines. If you touch price-update proposal generation,
  verify template filters are applied after/with defaults rather than replaced by
  them.

---

## 6. Renewal, termination, and contract extension pages

- **Sales-post renewal detection must be cached only inside one posting run:** repeated `SalesLine.IsContractRenewal()` and
  `SalesHeader.HasOnlyContractRenewalLines()` calls caused O(N²) scans and about
  25-28% batch CPU in renewal posting. Cache wrappers are appropriate, keyed by
  line/header `SystemId`, but clear them on both `OnBeforePostSalesDoc` and
  `OnAfterPostSalesDoc`; temporary buffers without `SystemId` use the uncached
  fallback.
- **Cache reset boundaries need multi-document proof:** post multiple
  documents in one run and verify normal lines are still posted correctly after a
  renewal document. A stale renewal cache can silently skip invoice/shipment line
  insertion or header creation.
- **Renewal Term page edits live in a temp `Subscription Line` buffer:** `ContractRenewalSelection.OnOpenPage` fills the buffer,
  `RenewalTermCtrl.OnValidate` writes to it, and `OnAfterGetRecord` must read the
  current buffer row by `Subscription Line Entry No.` before loading the stored
  line. Otherwise `CurrPage.Update` makes the field appear to reject the user's
  value.
- **Use different values on different renewal rows:** a test that
  enters the same Renewal Term on two lines does not prove per-line buffering.
  Set different terms, move to the next line, then return and assert the first
  line kept its own value.
- **Cancellation in days is not month-end rounding:**
  a past bug rounded `Cancellation Possible Until` to end of month when `Notice
  Period` was expressed in days. If you touch termination math, distinguish day
  formulas from month-aligned formulas just as invoice-period math does.
- **Renewal quote totals must honor `Billing Base Period`:** a past bug showed the base-period amount instead of the renewal-term
  amount on the Contract Renewal Quote. If you fix renewal totals, trace the
  amount period from `Subscription Line`.`Billing Base Period` through planned
  and quote lines, not just the visible price field.
- **Expose `Extend Contract` parameters as a page integration seam:**
  dependent apps need to open page **8002** and initialize it the same way as the
  existing usage-data flows. Widening the two parameter procedures is safe only if
  signatures and bodies stay the same and `OnOpenPage` still copies parameters
  into page state before validation.

---

## 7. Extensibility lessons specific to Subscription Billing

- **Do not make closed financial enums extensible unless runtime supports partner
  values:** `Rec. Billing Document Type` and `Usage Based Billing Doc.
  Type` model real invoice/credit-memo states; posting, deferral, filtering, and
  conversion code only understood built-in values. Keep them closed unless the
  full document flow handles custom values.
- **Grouping enums need an `else`/event path:** `Customer Rec. Billing
  Grouping` and `Vendor Rec. Billing Grouping` feed `ProcessBillingLines()` case
  statements. A partner value that compiles but creates no sales/purchase document
  is a runtime bug. Add a deliberate `IsHandled` extension point or keep the enum
  closed.
- **Do not expose temporary internal state:** helpers such as
  `SetUnitPriceAndUnitCostFromExtendContract()` / `ResetCalledFromExtendContract()`
  were called out because they reveal page-flow internals, not stable domain
  concepts. Prefer exposing a domain operation or the existing page parameter seam.
- **Extensibility regression tests can be tiny but must consume the new contract:** use a test app to call one newly public procedure or add a
  test-only enum value. The point is to catch accidental rollback of access and to
  prove the runtime path handles partner input.
- **Public cached APIs need key-aware behavior:** once a helper is
  callable by external apps, callers should not need to know to call a separate
  cache initializer. Direct lookup or key-aware cache refresh is the safe pattern.

---

## 8. Recurring agentic-review findings — fix these *before* handing off the fix

These are issues automated reviews repeatedly caught in Subscription
Billing changes. Pre-empting them saves review rounds.

- **Every parallel billing path you changed needs evidence.** Per-contract vs
  per-customer grouped sales headers, sales vs purchase headers, standard vs usage-based price assignment, and customer vs
  vendor deferrals each had separate code paths. Do not test only the
  path that first reproduced the bug.
- **Performance changes must prove behavior, not just speed.** If you add keys,
  caches, progress trackers, bulk updates, or transaction checkpoints in billing creation, prove
  amounts, document links, usage-data links, pricing/UoM hook behavior, no-GUI
  execution, and the intended rollback/transaction boundary.
- **A helper receiving a filtered record is a trap.** Rebuild critical filters
  inside the helper from stable identity (`Usage Data Import` entry number,
  document SystemId, billing-line key) when the helper changes status or cache
  state. `SetProcessedUsageDataBillingToOk` was fixed this way.
- **Record existence beats amount totals for billed-state checks.** Zero-value
  archived billing lines still count as billing and must lock the same start-date
  edits as non-zero lines.
- **Page buffer tests must distinguish rows.** If the bug is "the current renewal
  row overwrote another row," use different Renewal Terms and navigate back. If the test uses the same value everywhere, it proves too little.
- **Scope test cleanup to created subscription lines.** Broad `ModifyAll` on
  `Subscription Line` can make renewal/contract tests order-dependent in shared
  test companies; limit cleanup or assert the expected count first.
- **Interactive and automated billing errors are different contracts.** Raising
  populated `ErrorInfo` is right for interactive Billing Template/Billing Line
  paths; automated billing should keep logging behavior. Cover both sibling
  interactive helpers when both are changed.
- **Extensible enums need real runtime behavior.** Do not let a partner enum value
  compile and then skip document creation or filtering at runtime. Either add a
  proper extension point or keep the enum closed.
- **Public access changes are API contracts.** Removing `internal` is acceptable
  for stable domain helpers and page parameter seams, but not
  for volatile temporary state. Once public, name/signature/semantics
  become partner dependencies.
