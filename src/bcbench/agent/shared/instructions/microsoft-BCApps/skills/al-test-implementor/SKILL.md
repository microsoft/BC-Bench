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

- The AL MCP tools are available (see [AL tool resolution](#al-tool-resolution) below): either the VS Code AL extension (`ms-dynamics-smb.al`) with the AL workspace open, or the `al` MCP server configured in `.mcp.json` (Copilot CLI).
- A Business Central server instance is reachable and configured in `.vscode/launch.json`. The publish/test tools read the connection (`server`, `serverInstance`, `port`, `authentication`) from this file, so ensure it includes the developer-services `port`.
- The repository can run `init.ps1` (NAV/BC enlistment).

## AL tool resolution

The same AL MCP tools are exposed under **different tool IDs** depending on the host. Refer to the tools by their **base name** (e.g. `al_build`) throughout this skill and resolve the concrete ID for the current environment:

| Base name | VS Code AL extension | Copilot CLI (`al` MCP server) |
|-----------|----------------------|-------------------------------|
| `al_addproject` | *(implicit — workspace already open)* | `al-al_addproject` |
| `al_downloadsymbols` | *(implicit — extension manages symbols)* | `al-al_downloadsymbols` |
| `al_build` | `ms-dynamics-smb.al/al_build` | `al-al_build` |
| `al_publish` (without debug) | `ms-dynamics-smb.al/al_publish_without_debug` | `al-al_publish` (with `debug: false`) |
| `al_run_tests` | *(use PowerShell `Run-NAVALTests`, see STEP 7)* | `al-al_run_tests` |

**Detecting the environment:** load the tools via `tool_search` (pattern `al_`). If IDs are prefixed `ms-dynamics-smb.al/`, you are in VS Code; if prefixed `al-al_`, you are in Copilot CLI. Use whichever the search returns.

## Build & Run Tool Rules

**CRITICAL: Only use the designated AL tools for build/publish.**

- **ONLY** use the AL `al_build` tool for building AL projects.
- **ONLY** use the AL `al_publish` (without debug) tool for publishing.
- **NEVER** run `dotnet build`, `alc.exe`, `msbuild`, or any other build commands in the terminal.

If those deferred tools are not loaded yet, load them via `tool_search` before STEP 5. If they cannot be loaded (extension missing, workspace not AL, or `al` MCP server not configured), abort STEP 5 with a clear message — do not fall back to terminal builds.

### Copilot CLI only — project & symbol setup

In VS Code the open workspace already provides projects and symbols, so skip this whole subsection. In Copilot CLI:

**Register projects (dynamic — no restart).** `al_addproject` loads a project into the running server *without* restarting it; call it once per project (the folder containing each `app.json`). Register both the app under test and the test app.

**Target one app with `projectPath`.** `al_build`, `al_publish`, and `al_run_tests` accept `projectPath` and act on exactly that project. Always pass it so the tool targets the intended app when several are registered. This is the reliable way to switch between the app and its test app — no restart needed.

**`al_compile` is workspace-wide.** Unlike the above, `al_compile` (and `al_getdiagnostics` without a path) validate the *entire* registered workspace, not a single project — `al_addproject` does **not** narrow it. For single-app error checking use `al_build … onlyErrors=true projectPath=<app>` (or `ide-get_diagnostics`).

**Symbols come from the package cache, not `.alpackages`.** When the `al` MCP server is started with `--packagecachepath` (in `.mcp.json`), `al_build`/`al_compile` resolve dependency symbols from that folder and ignore per-project `.alpackages`. `AL1045`/`AL1022` ("package … could not be found in the package cache folders …") means the required symbol is absent from that folder — a symbol/config problem, not a code error (it cascades into `AL0791`/`AL0185`/`AL0132`). To fix:
- Prefer pointing `--packagecachepath` at the **country's** cache `Run/<CC>/AllExtensions` (derive `<CC>` from the app path: `App/Apps/<CC>/…`, `App/BCApps/src/Apps/<CC>/…`, `App/Layers/<CC>/…`; `W1` is the base). That folder is a **superset** that already contains the app, its test app, and test libraries — one path covers both, so you do **not** change it when switching between the app and its test.
- If `--packagecachepath` is not set, call `al_downloadsymbols` (with `projectPath` + the `launch.json` connection) to populate the project's `.alpackages`, then rebuild.

**The package cache is scanned only at startup.** If you change `--packagecachepath` (e.g. switch country) or add/update a dependency `.app` in that folder, the running server won't see it until the `al` MCP server is reloaded. Reload it via the **`/mcp`** command (this restarts just the server and preserves the session — do **not** restart the whole CLI). `al_addproject` does not trigger a rescan.

**Publish order:** publish the app under test **before** the test app (the test app depends on it).

## Defaults

When STEP 4 needs to make a choice (helper, assertion form, naming, structure), apply the rules in [references/defaults.md](./references/defaults.md). Load that file once during STEP 4b.

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

Write each approved test, then structure and refactor it to production quality. Sub-steps 4a–4c are mandatory in order. **Load [references/coding-rules.md](./references/coding-rules.md), [references/handlers.md](./references/handlers.md), and [references/table-relations.md](./references/table-relations.md) before writing any AL code — they always apply, regardless of the SUT.**

#### 4a. Look up Library helpers
Identify the Library helpers the test needs (master-data creators, posting routines, assertions) and look each one up in [references/library-api.md](./references/library-api.md) to confirm semantics, side effects, and (when relevant) `Prefer over:` notes before using it. Prefer existing Library procedures over hand-rolled record inserts or local helpers.

`library-api.md` ships pre-generated with the skill — do not regenerate at task time. (Maintainers: the regeneration script is [scripts/Scan-LibraryDocs.ps1](./scripts/Scan-LibraryDocs.ps1); it requires a BC source tree on disk and is run out-of-band when the Library API surface changes.)

#### 4b. Write the new test
For every choice (which random helper, which assert form, which master-data creator, how to structure the body), apply the rules in [references/defaults.md](./references/defaults.md) and [references/coding-rules.md](./references/coding-rules.md).

**For diff-driven runs**, each new test MUST exercise a specific changed line/branch from STEP 0's hunks: a new validation must be hit by at least one positive and one `asserterror` test; a new conditional branch must have a test that takes that branch; a new field must be set and asserted. **If a changed line is not covered by the proposed tests, add a test for it.** Do not silently leave a coverage gap.

Required structure (full rationale in [references/defaults.md](./references/defaults.md)):
- **First line after `begin`**: `// [FEATURE] [AI test skill <version>]`, where `<version>` is the value from the `<!-- Version: "X.Y" -->` marker at the top of this file (e.g. `// [FEATURE] [AI test skill 0.1]`).
- Naming: PascalCase, descriptive (e.g. `PostingDoesNotChangeBalanceWhenZeroAmount`).
- **Second line after `begin`**: `// [SCENARIO <work-item-id>] <one-line description>` (e.g. `// [SCENARIO 312912] Set Dimension Value with dot in the value as Department Filter`). The `<work-item-id>` is the ADO work item ID that motivated the test. Resolve it from (in order): (1) explicit ID in the prompt (`bug 12345`, `#67890`, `AB#54321`); (2) the parent agent's context if the skill was invoked by one. If no ID is available, in interactive mode ASK the user; in non-interactive mode emit `// [SCENARIO]` and call out the missing ID in the final report.
- Then `// [GIVEN]` / `// [WHEN]` / `// [THEN]` comments structure the body, each preceded by an empty line.
- Assertions: at least one `Assert.*` per test; for error paths, use `asserterror` plus **both** `Assert.ExpectedError` **and** `Assert.ExpectedErrorCode` (never `TestField` for assertions).
- **Respect the access decision from STEP 0.6.** If the SUT was reachable directly, declare `var X: Codeunit "<SutName>"` and call its public procedures. If STEP 0.6 routed the test through a public entry point (page action, posting routine, event), declare a variable for *that* entry-point object instead — never declare a variable for an internal codeunit / table / page that is not visible to the test app, the build will fail with `'... is inaccessible due to its protection level'`.
- **Do NOT add `[Scope('OnPrem')]`.** The attribute is deprecated.
- Drain handler queues at the end of any test that wired a `ConfirmHandler` / `ModalPageHandler` / `MessageHandler`: call `LibraryVariableStorage.AssertEmpty()`.

References to consult while implementing:
- [references/coding-rules.md](./references/coding-rules.md) — forbidden/required patterns, procedure order, library usage (always applies).
- [references/defaults.md](./references/defaults.md) — fallback rules and rationale (always loaded in 4b).
- [references/handlers.md](./references/handlers.md) — UI handler methods; always check whether the SUT calls `Confirm`, `Message`, `StrMenu`, or opens pages/reports/notifications.
- [references/table-relations.md](./references/table-relations.md) — always check `TableRelation` constraints before inserting test data.
- [references/library-api.md](./references/library-api.md) — looked up in 4a for each Library helper the new test calls.

#### 4c. Review & refactor to production quality
After writing the tests (and before build), do a dedicated quality pass over everything written — this mirrors the standalone review the AL Test agent performs:
1. **Structure**: every test has `// [FEATURE]`, `// [SCENARIO]`, `Initialize();`, and empty-line-separated `[GIVEN]`/`[WHEN]`/`[THEN]` comments.
2. **Procedure order**: Test procedures first, then `Initialize`, then local helpers (`Verify*` for verification), then handlers — move procedures if needed.
3. **Replace local helpers with library calls**: for any hand-rolled setup, search [references/library-api.md](./references/library-api.md) for an existing Library procedure; if one exists, use it and delete the local helper. Declare new library variables in the global `var` section and remove unused variables.
4. **Coding rules**: apply [references/coding-rules.md](./references/coding-rules.md) — no conditionals in the test body, no `TestField` for assertions, `asserterror` paths use both `Assert.ExpectedError` AND `Assert.ExpectedErrorCode`, no `Commit` in helpers/handlers, handlers only set values.

### STEP 5 — Build (max 3 attempts)
Build the test app with the AL `al_build` tool, passing `projectPath` = the test app folder (resolve the ID per [AL tool resolution](#al-tool-resolution); in Copilot CLI ensure the [project & symbol setup](#copilot-cli-only--project--symbol-setup) is done first). On compile errors, fix and rebuild. **Distinguish symbol/config errors from code errors:** `AL1045`/`AL1022` (package cache) are not fixable by editing test code — resolve them via the package-cache guidance in that setup subsection (and reload with `/mcp` if you changed the cache), then rebuild without counting it as a code-fix attempt. **Cap the code build/fix loop at 3 attempts.** If the test app still does not compile after the 3rd attempt, stop. Report the remaining compile errors and the changes made on each attempt; do not proceed to STEP 6.

### STEP 6 — Publish
Publish the test app with the AL `al_publish` (without debug) tool, passing `projectPath` = the test app folder (resolve the ID per [AL tool resolution](#al-tool-resolution)). If you also (re)built the app under test, publish **it first**, then the test app.

### STEP 7 — Run tests
Run the published tests using whichever path fits the environment:

- **Copilot CLI:** use the `al_run_tests` MCP tool with the test `codeunitId` and `projectPath` (the test app folder); connection is read from `launch.json`.
- **VS Code / PowerShell:** follow [references/run-al-tests.md](./references/run-al-tests.md) **strictly in order**. The key rule: `init.ps1` and `Run-NAVALTests` MUST be invoked in a SINGLE combined PowerShell command — terminal sessions lose their initialized environment between tool calls.

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
