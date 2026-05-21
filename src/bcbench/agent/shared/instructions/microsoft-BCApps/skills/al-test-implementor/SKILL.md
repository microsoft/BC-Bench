---
name: al-test-implementor
description: "Writes, builds, publishes, and runs AL tests (positive, negative, and edge cases) for Microsoft Dynamics 365 Business Central (BC / NAV). Use when asked to implement, create, generate, or add AL test coverage for a codeunit / table / page / report / procedure, reproduce a bug, verify a fix, or cover a new feature with a test, generate tests for staged / unstaged / branch / PR changes (e.g. 'tests for my changes', 'tests for changes in codeunit X'), produce BC-Bench test-generation outputs, or when chained from another agent that just produced an AL fix or feature."
argument-hint: "example: implement tests for staged changes | tests for X procedure in Y.codeunit.al"
---
<!-- Version: "0.1" -->

# AL Test Implementor

Implements or generates AL tests for Microsoft Dynamics 365 Business Central (BC / NAV), covering positive, negative, and edge cases. Builds, publishes, and runs the tests end-to-end (or stops after writing the test if the caller forbids running it).

## When to Use

- User asks to implement, write, or generate AL tests (any phrasing: "write a test", "generate a test", "add test coverage", "create test case").
- User wants tests for **staged**, **unstaged**, branch, or PR changes ("tests for staged changes", "tests for my changes", "tests for changes in codeunit X", "cover the diff with tests").
- User wants a test that reproduces an issue described in a bug / problem statement, or that verifies a fix.
- The prompt mentions an AL codeunit, table, page, or report and requests a test for it.
- A parent agent (e.g. bug-fix or feature-implementation agent) has just produced AL changes and is now invoking this skill to add covering tests.

## Invocation Mode

Decide upfront which mode applies — it controls whether STEP 1 / STEP 2 (propose + wait for approval) run.

- **Interactive mode** (default when a human is driving the chat): run STEP 1 and STEP 2 as written.
- **Non-interactive mode** — skip STEP 1 and STEP 2 (no proposal, no approval gate), implement whatever set of tests the skill judges necessary to cover the SUT / diff, and report results at the end. Use non-interactive mode when ANY of these is true:
  - This skill was invoked by another agent / subagent (no human can approve mid-run).
  - The prompt explicitly says "no questions", "don't ask", "auto", "non-interactive", "end-to-end", or similar.
  - The prompt is a diff-driven request ("tests for staged/unstaged/branch changes") AND the user named no specific scenarios.

  Coverage rule (no hard cap): decide the test count from the SUT / diff itself — every changed public surface, branch, validation, and new field must be exercised by at least one positive and (where applicable) one `asserterror` test, plus edge cases the change clearly introduces (new boundaries, new states, new error messages). Do not pad with redundant tests; do not skip needed coverage to stay "small".

  In non-interactive mode you MUST still go through STEP 0 and STEPS 3–8 in order.

## Prerequisites

- The AL extension (`ms-dynamics-smb.al`) is installed and the AL workspace is open.
- A Business Central server instance is reachable and configured in `.vscode/launch.json`.
- The repository can run `init.ps1` (NAV/BC enlistment).

## Build & Run Tool Rules

**CRITICAL: Only use the designated AL tools for build/publish.**

- **ONLY** use the AL extension's build tool (`ms-dynamics-smb.al/al_build`) for building AL projects.
- **ONLY** use the AL extension's publish-without-debug tool (`ms-dynamics-smb.al/al_publish_without_debug`) for publishing.
- **NEVER** run `dotnet build`, `alc.exe`, `msbuild`, or any other build commands in the terminal.

If those deferred tools are not loaded yet, load them via `tool_search` before STEP 5. If they cannot be loaded (extension missing, workspace not AL), abort STEP 5 with a clear message — do not fall back to terminal builds.

## Defaults

When STEP 4 has no example to mirror (or the example does not constrain a choice), apply the rules in [references/defaults.md](./references/defaults.md). Load that file once during STEP 4e.

## Workflow

**CRITICAL: Do not proceed to the next step until the previous step is done.**

**MANDATORY: After developer approval in STEP 2 (interactive mode) or after STEP 0 (non-interactive mode), complete ALL remaining steps (3–8) without stopping.**

### STEP 0 — Identify the SUT(s)

The SUT is the production AL object(s) the new tests will exercise. Resolve **paths only** here — do NOT create files, IDs, or codeunits in this step.

1. **Explicit file/object in prompt** (`Y.codeunit.al`, "procedure X in codeunit Y") → use that file directly. If the file is itself a `Subtype = Test` codeunit, infer the production SUT using these signals (in order):
   - Look at `Codeunit::"<name>"` references and `var X: Codeunit "<name>"` declarations inside the test body — the most-referenced production codeunit is the SUT.
   - Failing that, look at which `Library*` codeunits the test uses to identify the feature area, then find production objects in that area.
   - Last resort only: try the suffix-strip heuristic (`<X>Tests` → `<X>`) and verify the candidate file actually exists. **Never silently pick a SUT this way without checking.**
   - In interactive mode, when these signals disagree or none resolve unambiguously, ASK the user.
2. **Diff-driven prompt** ("staged changes", "unstaged changes", "my changes", "this branch", "this PR", "changes in codeunit X") → derive SUTs from git:
   - Staged: `git diff --cached --name-only --diff-filter=AMR`
   - Unstaged: `git diff --name-only --diff-filter=AMR`
   - Branch / PR: `git diff --name-only --diff-filter=AMR <base>...HEAD`. Resolve `<base>` in this order: (1) explicit base named in the prompt; (2) the upstream tracking branch (`git rev-parse --abbrev-ref --symbolic-full-name @{u}`); (3) the remote HEAD (`git symbolic-ref --short refs/remotes/origin/HEAD`, typically `origin/main` or `origin/master`); (4) `main` or `master` if either exists locally. **If none of these resolve, abort STEP 0 with a clear message** ("Could not determine diff base — re-invoke with the base branch named explicitly, e.g. 'tests for changes since origin/main'") and stop. Do not silently invent a base.
   - Filter to AL production files only: keep `*.al` under `App/` (or any non-test app folder); **drop** files whose codeunit declares `Subtype = Test`, files under any `*Test*` / `*Tests*` folder, and non-AL files (`*.xlf`, `*.json`, images, etc.).
   - Also capture the changed *hunks* (`git diff [--cached] -- <file>`) — STEP 4e must target the new/changed branches and validations specifically.
3. **Parent-agent invocation with no explicit SUT** → ask the parent agent's prompt for the SUT path; if absent, fall back to the diff-driven discovery above against unstaged + staged changes.
4. **Multiple SUTs** → process each SUT through STEPS 4a–4e. Group tests for the same production object into the same test codeunit.
5. **Plan (don't create) the destination test file** for each SUT — record the intended path and codeunit name, but do not write to disk yet:
   - Prefer the existing test app for the SUT's app (sibling folder, typically named `<App>.Test` / `<App> Tests` — confirm by reading nearby `app.json` files).
   - If an existing test codeunit already targets the SUT (search for `Subtype = Test` codeunits that reference the SUT), reuse it.
   - Otherwise plan a new codeunit named `<SutName> Tests` with a fresh ID from the test app's `idRanges` in `app.json`. **Actual file/codeunit creation happens in STEP 3, after STEP 2 approval (interactive) or immediately (non-interactive).**

6. **Check SUT accessibility from the test app.** Read the SUT object header for an `Access` modifier and read both `app.json` files for `internalsVisibleTo` entries. The combinations are:
   - SUT is `Access = Public` (or has no modifier and the app's `app.json` does not set a default of `Internal`) → fine, the test can declare `var X: Codeunit "<SutName>"` directly.
   - SUT is `Access = Internal` (or the SUT app defaults to internal) AND the SUT app's `app.json` lists the test app under `internalsVisibleTo` → fine.
   - SUT is `Access = Internal` AND no `internalsVisibleTo` link → the test cannot reference the codeunit / table / page directly. **Pick a public entry point instead** (a public procedure on a public facade codeunit, a page action, a posting routine, an event the SUT subscribes to). If no public entry point exercises the changed lines, in interactive mode flag this to the user and ask whether to (a) add the test app to `internalsVisibleTo`, (b) test via a different public surface, or (c) skip. In non-interactive mode, abort STEP 0 with a clear message naming the SUT and the missing access path — do not write a test that will not compile.

### STEP 0.7 — Classify the SUT *(runs in both modes)*

All scripts are bundled in the skill folder. Run them from the skill root (the directory containing this SKILL.md file). They have no external dependencies.

Run the classifier and **print its JSON output as a fenced code block**:

```powershell
pwsh -NoProfile -File ./scripts/Classify-Sut.ps1 -Path "<absolute-path-to-SUT>"
```

Output: `{"subject":"<label>","interaction":"<label>"}`. Capture both values — they are required inputs to STEP 0.8 and STEP 4c.

Labels: `subject` = posting / pages / reports / xml-integration / calculation / setup / permissions / other; `interaction` = direct-call / confirm-dialog / modal-page / report-request / notification / asserterror / none.

**Do not invent or guess the classification. Run the script. If it fails, report the error and stop.**

### STEP 0.8 — Retrieve example test(s) *(runs in both modes)*

Run the retrieval script immediately after STEP 0.7, using the classification just captured:

```powershell
pwsh -NoProfile -File ./scripts/Find-SimilarTests.ps1 `
    -SutPath "<absolute-path-to-SUT>" `
    -PrTitle "<work-item title or short scenario>" `
    -Subject "<subject from 0.7>" `
    -Interaction "<interaction from 0.7>" `
    -TopN 3
```

The script returns top-N corpus rows as JSON (`file`, `name`, `body`, `callsLibraries`, `score`).

**In interactive mode**: print a one-line summary per example (`<name> — score <N.NN>`) so the developer can see what will be mirrored before approving tests in STEP 2.
**In non-interactive mode**: capture the results silently — no summary line needed, but the data is required input for the evidence block in STEP 4d.5.

If retrieval returns nothing useful (empty or all scores < 0.3), state this explicitly: *"No useful examples retrieved — STEP 4e will rely on defaults.md entirely."* Do not silently discard the result.

**Do not skip this step.** The corpus results are required inputs to STEP 4c and the evidence block in STEP 4d.5.

### STEP 1 — Propose tests *(interactive mode only — skip in non-interactive mode)*
For each SUT (in the order found in STEP 0), present a per-SUT block containing:
- The SUT path.
- The planned destination test file (from STEP 0.5) — flag if it will be newly created.
- A list of proposed tests (positive, negative, edge cases). For diff-driven runs, anchor each proposed test to a specific changed line/branch in the diff.

After all per-SUT blocks have been printed, ask for **one batched approval** covering everything. Do not interleave a separate approval gate per SUT.

### STEP 2 — Wait for batched approval (MANDATORY STOP POINT — interactive mode only)
Do NOT proceed until the developer explicitly approves or selects tests across the per-SUT blocks shown in STEP 1.
- Approves all → implement everything.
- Selects some (e.g. "SUT A: tests 1, 3; SUT B: skip") → implement only those.
- Requests changes → revise the affected per-SUT block(s) and ask again.

**In interactive mode, NEVER skip this step. NEVER assume approval.** Once approval is received (or non-interactive mode applies), you MUST continue through ALL remaining steps without stopping.

### STEP 3 — Open / create the target test file
For each approved SUT, open the planned test file from STEP 0.5. If it does not yet exist, create it now with the codeunit skeleton (`codeunit <id> "<SutName> Tests" { Subtype = Test; ... }`) using the ID reserved in STEP 0.5. **This is the first step that writes to disk.**

### STEP 4 — Implement only the approved tests

STEP 4 is corpus-grounded: inspect the examples captured in STEP 0.8, resolve the Library helpers they call, emit the mandatory evidence block, then write the AL test. Sub-steps 4a–4e are mandatory in order.

#### 4a. Confirm classification from STEP 0.7

State the `{subject, interaction}` values captured in STEP 0.7. **Do not re-run Classify-Sut.ps1.** If STEP 0.7 was skipped (classification is missing), stop — go back and run STEP 0.7 before continuing. For diff-driven runs, also keep the changed-hunks summary handy — 4e must target those lines.

#### 4b. Confirm examples from STEP 0.8

State the top-N examples (name + score) captured in STEP 0.8. **Do not re-run Find-SimilarTests.ps1.** If STEP 0.8 was skipped (examples are missing), stop — go back and run STEP 0.8 before continuing. If STEP 0.8 explicitly reported no useful results, state *"No examples — using defaults.md entirely"* and proceed.

#### 4c. Inspect example bodies
Read the bodies of the top picks. List the Library procedures they call (the `callsLibraries` field is the easy index). Note their structure: which Library is used to create master data (customer, vendor, item, GL account), how the SUT is invoked (direct call / posting routine / page action / report run), what assertion forms close each `[THEN]`.

#### 4d. Look up Library helpers
For each Library procedure called by the example(s), look it up in [references/library-api.md](./references/library-api.md) to confirm semantics, side effects, and (when relevant) `Prefer over:` notes before reusing it in the new test.

`library-api.md` ships pre-generated with the skill — do not regenerate at task time. (Maintainers: the regeneration script is [scripts/Scan-LibraryDocs.ps1](./scripts/Scan-LibraryDocs.ps1); it requires a BC source tree on disk and is run out-of-band when the Library API surface changes.)

#### 4d.5 — Emit evidence block *(mandatory in both modes)*

**Do not write any AL code until this block is printed.** Fill every field with the actual values from STEP 0.7, 0.8, 4c, and 4d. Write `none` for any field that is genuinely empty — never omit or abbreviate the block.

```
=== STEP 4 EVIDENCE ===
SUT classification : <subject> / <interaction>
Retrieved examples : <test name> (score <N.NN>)
                     <test name> (score <N.NN>)
Library helpers    : <Procedure1>, <Procedure2>, ...
Verified in api.md : ✓ <Procedure1> — <one-line semantic note from library-api.md>
                     ✓ <Procedure2> — <one-line semantic note>
======================
```

If any choice in the upcoming 4e deviates from what the example uses (different helper, different assertion style, different data-creation pattern), add a `Deviation:` line for each one with a reason. Random or unexplained deviations are not allowed.

#### 4e. Write the new test
Mirror the example's structure adapted to the SUT. For every choice that the example does **not** constrain (e.g. which random helper, which assert form, which customer creator), apply the rules in [references/defaults.md](./references/defaults.md).

**For diff-driven runs**, each new test MUST exercise a specific changed line/branch from STEP 0's hunks: a new validation must be hit by at least one positive and one `asserterror` test; a new conditional branch must have a test that takes that branch; a new field must be set and asserted. **If a changed line is not covered by the proposed tests, add a test for it.** Do not silently leave a coverage gap.

Required structure (full rationale in [references/defaults.md](./references/defaults.md)):
- **First line after `begin`**: `// [FEATURE] [AI test skill <version>]`, where `<version>` is the value from the `<!-- Version: "X.Y" -->` marker at the top of this file (e.g. `// [FEATURE] [AI test skill 0.1]`).
- Naming: PascalCase, descriptive (e.g. `PostingDoesNotChangeBalanceWhenZeroAmount`).
- **Second line after `begin`**: `// [SCENARIO <work-item-id>] <one-line description>` (e.g. `// [SCENARIO 312912] Set Dimension Value with dot in the value as Department Filter`). The `<work-item-id>` is the ADO work item ID that motivated the test. Resolve it from (in order): (1) explicit ID in the prompt (`bug 12345`, `#67890`, `AB#54321`); (2) the work-item ID parsed from the `-PrTitle` you passed to retrieval (3) the parent agent's context if the skill was invoked by one. If no ID is available, in interactive mode ASK the user; in non-interactive mode emit `// [SCENARIO]` and call out the missing ID in the final report.
- Then `// [GIVEN]` / `// [WHEN]` / `// [THEN]` comments structure the body, each preceded by an empty line.
- Assertions: at least one `Assert.*` per test; for error paths, use `asserterror` plus `Assert.ExpectedError` or `Assert.ExpectedErrorCode`.
- **Respect the access decision from STEP 0.6.** If the SUT was reachable directly, declare `var X: Codeunit "<SutName>"` and call its public procedures. If STEP 0.6 routed the test through a public entry point (page action, posting routine, event), declare a variable for *that* entry-point object instead — never declare a variable for an internal codeunit / table / page that is not visible to the test app, the build will fail with `'... is inaccessible due to its protection level'`.
- **Do NOT add `[Scope('OnPrem')]`.** The attribute is deprecated.
- Drain handler queues at the end of any test that wired a `ConfirmHandler` / `ModalPageHandler` / `MessageHandler`: call `LibraryVariableStorage.AssertEmpty()`.

References to consult while implementing:
- [references/defaults.md](./references/defaults.md) — fallback rules and rationale (always loaded in 4e).
- [references/handlers.md](./references/handlers.md) — required when the SUT calls `Confirm`, `Message`, `StrMenu`, opens pages/reports/notifications, etc.
- [references/table-relations.md](./references/table-relations.md) — required when inserting test data into tables with `TableRelation` constraints.
- [references/library-api.md](./references/library-api.md) — looked up in 4d for each Library helper the new test calls.

### STEP 5 — Build (max 3 attempts)
Build the test app with the AL build tool (`ms-dynamics-smb.al/al_build`). On compile errors, fix and rebuild. **Cap the build/fix loop at 3 attempts.** If the test app still does not compile after the 3rd attempt, stop. Report the remaining compile errors and the changes made on each attempt; do not proceed to STEP 6.

### STEP 6 — Publish
Publish the test app with the AL publish-without-debug tool (`ms-dynamics-smb.al/al_publish_without_debug`).

### STEP 7 — Run tests
Follow [references/run-al-tests.md](./references/run-al-tests.md) **strictly in order**. The key rule: `init.ps1` and `Run-NAVALTests` MUST be invoked in a SINGLE combined PowerShell command — terminal sessions lose their initialized environment between tool calls.

### STEP 8 — Verify
Verify all tests pass. Do NOT attempt fixes silently — if any test fails, the failure handling depends on the invocation mode:

- **Interactive mode**: report up to 3 likely causes and suggest the user invoke an AL test troubleshooting agent (e.g. `ALTestTroubleshooter` if available in the workspace) to investigate. Stop.
- **Non-interactive mode**: do NOT auto-invoke a troubleshooter and do NOT roll back the test code. Return a structured failure summary (failing test names, the assertion / error message for each, the likely cause, and the path to the new test file) so the calling agent can decide whether to retry, escalate, or revert. The new tests stay on disk so the parent agent can inspect them.

**COMPLETION REQUIREMENT: The task is NOT complete until STEP 8 is finished.**

## Output

Return to the user:
1. Final list of implemented tests (names + scenarios).
2. Build result and any fixes applied.
3. Publish result.
4. Test run results — pass/fail per test, plus failure analysis if any failed.
