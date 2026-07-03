# AL Test Coding Rules

These rules always apply when writing or refactoring AL tests. They mirror the AL Test agent's coding standard and are enforced in STEP 4b (write) and STEP 4c (review & refactor).

## Test Comments and Tags

**CRITICAL: Do NOT add `SCENARIO` tags with arbitrary numbers unless the number is a real ADO work item ID.**

- **NEVER** invent a `// [SCENARIO 123456]` number — that form links the test to an actual ADO work item. Only use a number you resolved from the prompt or parent-agent context.
- If no work-item ID is available, use `// [SCENARIO] <one-line description>` (no number) and flag the missing ID in the final report.
- **DO** add `// [GIVEN]`, `// [WHEN]`, `// [THEN]` comments to structure the body.
- In COMMENTS, refer to entities with 1-2 letters: `"C"`, `"V"`, `"C1"` (e.g. `// [GIVEN] Customer "C" with Sales Invoice "SI"`).
- Variable names must be FULL names, not abbreviated: `CustomerNo`, `VendorNo`, `ItemNo` (NOT `C`, `V`, `CustNo`).
- Use rounded amounts without decimals where the value is not otherwise constrained.

## Codeunit Procedure Order (MUST be enforced — move procedures if needed)

1. Test procedures (with `[Test]` attribute) — MUST come FIRST
2. `Initialize` procedure
3. Local helper procedures (use `Verify` prefix for verification procedures)
4. Handler procedures (at the end of the codeunit)

## Coding Standard

### Forbidden patterns
- ❌ Conditional statements (`if`/`else`) in the test body — split into separate tests instead.
- ❌ DotNet variables.
- ❌ Interface invocations — use implementation codeunits instead.
- ❌ Verification inside handler procedures.
- ❌ `Commit` calls in helper or handler procedures (only allowed in the test body).
- ❌ Modifying the working date (unless absolutely necessary).
- ❌ `TestField` for assertions — use `Assert.AreEqual` instead.
- ❌ `[Scope('OnPrem')]` — the attribute is deprecated.

### Required patterns
- ✅ After `asserterror` in `[WHEN]`, add **both** `Assert.ExpectedError()` **AND** `Assert.ExpectedErrorCode()` in `[THEN]`.
- ✅ At least one `Assert.*` per test.
- ✅ Multiple verifications should use a local `Verify*` procedure.
- ✅ Reuse existing local procedures when possible; prefer Library procedures over local helpers.
- ✅ Handler procedures should only set values, never verify.
- ✅ Drain handler queues at the end of any test that wired a `ConfirmHandler` / `ModalPageHandler` / `MessageHandler`: call `LibraryVariableStorage.AssertEmpty()`.

### Amount handling
- Do NOT re-assign or redefine amounts in the test body if they are already defined in a helper function — trust the helper's default and omit the assignment.
- If an amount must be verified, create a new local variable and assign it from the helper function's return value.

## Test Library Usage

1. **Global variable declaration** — all library variables MUST be declared in the global `var` section. Do NOT pass libraries as function parameters.
2. **Library Variable Storage** — use it to pass data between test and handler procedures. If used, MUST end the test with `LibraryVariableStorage.AssertEmpty()`.
3. **Library Setup Storage** — use it in the `Initialize` procedure if any setup table is modified in the tests.

### Common libraries

| Library | Purpose |
|---------|---------|
| Assert | Assertions |
| Library Sales | Sales operations (customer, sales invoice) |
| Library Purchase | Purchase operations (vendor, purchase invoice) |
| Library ERM | General ERM (general journal, G/L account) |
| Library Utility | Random test data, number series, generic record operations |
| Library Random | Random numbers, decimals, dates, text strings |
| Library Inventory | Items, units of measure, inventory setup and posting |
| Library Dimension | Dimensions and dimension values |
| Library Journals | General journal lines, batches, templates |
| Library Marketing | Contacts and marketing entities |
| Library Fixed Asset | Fixed asset operations |
| Library Warehouse | Locations, bins, zones, warehouse documents |
| Library Manufacturing | Production orders, BOMs, routings, work centers |
| Library XPath XML Reader | Read and verify XML content |
| Library Variable Storage | Pass data between test and handlers |
| Library Lower Permissions | Setting/managing permission sets |

Look up exact procedure signatures and semantics in [library-api.md](./library-api.md) before using a helper.

## Common Fixes

**Missing `Initialize()`** — it must come immediately after the `// [SCENARIO]` line, before the first `// [GIVEN]`.

**Inline record creation → Library usage**
```al
// BEFORE (wrong):
Customer.Init();
Customer."No." := 'CUST001';
Customer.Insert();

// AFTER (correct):
LibrarySales.CreateCustomer(Customer);
```

**Conditional in test → separate tests** — replace an `if/else` that asserts different things per branch with two independent `[Test]` procedures.
