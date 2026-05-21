# AL Test Implementor — Defaults

## Priority rule: examples override defaults

When at least one example was retrieved in STEP 0.8 with score ≥ 0.3, the example's concrete choices **take precedence over every row in this table** for the same category. Use a default only when the example does **not** constrain that particular choice.

**Silent deviations from the example are not allowed.** If you use a different helper, assertion style, or data-creation pattern than the example uses, record it as a `Deviation:` line in the STEP 4d.5 evidence block with a reason.

Specific examples of what *"the example constrains"* means:
- Example uses `LibraryRandom.RandDecInRange(100, 200, 2)` → do **not** hardcode `100` or call `RandDec(max, 2)` for amounts.
- Example uses `LibraryIRS1099Document.MockFormDocumentForVendor(...)` → do **not** hand-roll a direct `IRS1099FormDocHeader.Insert()` for the same data.
- Example calls `Assert.AreEqual(expected, actual, msg)` → do **not** use `TestField` for the same kind of equality assertion.

When no example was retrieved (STEP 0.8 returned nothing useful), apply every row in this table.

---

These defaults are distilled from 942 historical test procedures. When no example constrains a choice, pick the entry from this table.

| Need | Default | Why |
|---|---|---|
| Author / origin tag | First line after `begin` is `// [FEATURE] [AI test skill <version>]`, where `<version>` is the value from the `<!-- Version: "X.Y" -->` marker at the top of `SKILL.md` (e.g. `// [FEATURE] [AI test skill 0.1]`). | Mirrors the `ALTestImplementor` agent convention; lets reviewers trace which automated author wrote the test |
| Naming | `PascalCase`, descriptive, ~30–60 chars | 91% of corpus names are PascalCase, avg ~47 chars |
| Scenario tag | `// [SCENARIO <work-item-id>] <one-line description>` (e.g. `// [SCENARIO 312912] Posting fails when amount is zero`) immediately after the `[FEATURE]` line. Resolve `<work-item-id>` from (in order): explicit ID in the prompt (`bug 12345`, `#67890`, `AB#54321`); the ID parsed from the `-PrTitle` passed to retrieval; the parent agent's context. If unknown, in interactive mode ASK; in non-interactive mode use `0` and flag it in the final report. | The `[SCENARIO 123456]` form links the test to its ADO work item — the dominant convention in the corpus |
| Body structure | Each `// [GIVEN]` / `// [WHEN]` / `// [THEN]` comment preceded by an empty line, interleaved with code | 91% of corpus tests use the GWT structure |
| `[Scope('OnPrem')]` | **Do NOT add it** | Deprecated — only legacy rows carry it (67% of corpus, but new tests must not) |
| Internal SUT access | Before declaring `var X: Codeunit "<SutName>"` (or `Record`, `Page`, etc.), check the SUT object header for `Access = Internal` and the SUT app's `app.json` for an `internalsVisibleTo` entry naming the test app. If the SUT is internal AND not exposed via `internalsVisibleTo`, **do not declare a variable for it** — the test app cannot see it and the build will fail with `'... is inaccessible due to its protection level'`. Test through a public entry point (public facade procedure, page action, posting routine, subscribed event) instead. | Compile-time access modifier rule — most common cause of "declared but won't compile" failures |
| Customer (return Code) | `LibrarySales.CreateCustomerNo()` | Top customer creator (42 calls); use `CreateCustomer(Customer)` only when you need the record |
| Vendor | `LibraryPurchase.CreateVendor(Vendor)` then read `Vendor."No."` | Top vendor creator (14 calls); `CreateVendorNo()` (12) is the equivalent shortcut |
| Item (return Code) | `LibraryInventory.CreateItemNo()` | Top item creator (17 calls); `CreateItem(Item)` (14) when you need the record |
| GL account (return Code) | `LibraryERM.CreateGLAccountNo()` | Top GL creator (18 calls) |
| Random decimal | `LibraryRandom.RandDecInRange(min, max, precision)` | Top random helper (101 calls); use `RandDec(...)` only when 0..max is OK |
| Random integer | `LibraryRandom.RandIntInRange(min, max)` | 25 calls; `RandInt(max)` (18) when 1..max is OK |
| Random unique code/text | `LibraryUtility.GenerateGUID()` | 100 calls; pads to 10 chars, fits Code[20] |
| Equality assertion | `Assert.AreEqual(expected, actual, msg)` | Top assert (166); use `AreNotEqual` (41) for negative cases |
| Truthy / falsy | `Assert.IsTrue(cond, msg)` / `Assert.IsFalse(cond, msg)` | 103 / 53 calls |
| Error path | `asserterror <call>` + `Assert.ExpectedError(<text>)` (or `ExpectedErrorCode`) | 53 / 41 calls |
| Confirm dialog handler | `[ConfirmHandler]` plus `LibraryVariableStorage.Enqueue(true/false)` before the SUT call; dequeue inside the handler with `LibraryVariableStorage.DequeueBoolean()` | 105 corpus tests use `ConfirmHandler` |
| Handler-queue cleanup | End any test that wired a `ConfirmHandler` / `ModalPageHandler` / `MessageHandler` with `LibraryVariableStorage.AssertEmpty()` | 122 calls — most-used helper in the corpus |
| Posting (Sales) | `LibrarySales.PostSalesDocument(SalesHeader, ShipReceive, Invoice)` | 41 calls |
| Posting (Purchase) | `LibraryPurchase.PostPurchaseDocument(PurchHeader, ShipReceive, Invoice)` | 12 calls |
| Posting (G/L journal) | `LibraryERM.PostGeneralJnlLine(GenJnlLine)` | 50 calls |
| Per-codeunit setup | Optional `Initialize()` local procedure called from each `[Test]` — guard expensive setup with a `IsInitialized` flag | 48% of corpus tests follow this pattern |
