<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Tool Usage Reference

Detailed command syntax and best practices for `bc-fix-bug` operations.

## Plan File

- Phase 1 writes the plan directly to `<temp_dir>/plan.md` using `templates/plan-template.md`, using
  the literal bug ID `BENCH`. There is no work item to post it to, and no `--plan-file` entry point:
  every run starts from `problem/README.md`.
- It carries a markdown body with a mandatory Test Strategy; downstream phases receive it as
  `plan_content`, and it reaches test-implementor to drive the required reproducing test.

## Code Changes

- **Edit**: Make targeted fixes using exact string replacement
- **Write**: Create the new test file that reproduces the bug - a reproducing test is always
  required in this benchmark
- Keep changes minimal and focused
- Do not add ticket-reference comments in code - there is no bug ID or PR to link the change to

## Compile / Publish / Test Reference

The BC container is provisioned before this skill runs; the AL MCP server is attached only when the harness runs with `--al-mcp`. Resolve every tool through `compatibility.md`; use the first advertised implementation for each capability and never hard-code one host's tool name. When no AL tool is advertised the run is in **static mode** (`compatibility.md` → "AL tooling modes") and none of this section applies - follow `shared-rules.md` Rule 2a instead.

| Capability | Preferred resolution | Fallback / notes |
|------------|----------------------|------------------|
| Build AL projects | AL build capability (`al_build`, with detected host prefix) | Build every modified project with all-project scope when available. |
| Publish AL apps | AL publish capability (`al_publish`, with detected host prefix) | Pass `skipBuild: true` with the artifact path from the preceding build; use dependency-chain publish when supported so test apps are deployed in order. |
| Diagnostics | AL diagnostics capability (`al_getdiagnostics`) | Parse build output only when diagnostics are unavailable. |
| Symbols | AL symbol capability (`al_downloadsymbols` or `al_symbolsearch`) | `al_downloadsymbols` also serves as the pre-publish session warm-up required by `shared-rules.md`. |
| Run AL tests | AL test capability (`al_run_tests`, with detected host prefix) | No PowerShell fallback: BcContainerHelper is denied by the block hook. If `al_build` is advertised but the test tool is not, stop and report the failure. If no AL tool at all is advertised, that is static mode - see `shared-rules.md` Rule 2a. |

**In static mode this whole table is inapplicable.** No AL tool is advertised, nothing is compiled,
published or executed, and the static counterparts in `shared-rules.md` Rule 2a apply instead.

**Rules:**

- Build EVERY project you modify. The AL build capability should compile the whole workspace when all-project scope is available.
- Publish with the AL publish capability after a successful build. Use dependency-chain publish so dependent apps, including the test app, come along in order.
- Publish the artifact you just built: pass `skipBuild: true` plus the `.app` path the build returned (or `testApp.path`). `al_publish` otherwise re-runs a full build inside the publish call, which on large projects exhausts the call budget before anything is deployed. Never pass `skipBuild: true` without a successful build in the same iteration.
- Connection values, the pre-publish warm-up and the publish-call journal are defined once in `shared-rules.md` (Rule 2). Follow them there; they are not restated here.
- Run tests with the AL test capability (`al_run_tests`). There is no PowerShell fallback.
- Tests will use old code if you skip publishing.
- Fix compilation errors immediately, inspecting with the AL diagnostics capability when available, before proceeding.

## Test Execution

**IMPORTANT: A reproducing test is always required in this benchmark. Follow the test-implementor
phase document for initial test creation.**

- **test-implementor** (`phases/test-implementor.md`): **REQUIRED** for
  initial test creation
  - **Phase 2 (Baseline Loop - Iteration 1)**: Create new tests
    - The phase implements tests based on bug scenarios
    - Tests are created but not run by the phase document
    - You will build, publish, and run them in the baseline loop

- **AL capabilities + container**: Used in baseline and fix loops for build, publish, and test -
  **executed mode only**. In static mode (no AL tool advertised) skip all of the below and follow
  `shared-rules.md` Rule 2a.
  - **Phase 2 (Baseline Loop)**: Build, publish, run tests each iteration
    - Expect tests to fail (reproducing the bug)
    - Adjust tests if they don't fail correctly
    - Continue until baseline established (max 5 iterations)
  - **Phase 3 (Fix Loop)**: Build, publish, run tests each iteration
    - Expect tests to pass once fix is correct
    - Adjust fix if tests still fail
    - Continue until tests pass (max 5 iterations)
  - **Notes**:
    - The environment is provided out-of-the-box; do not set it up
    - `al_build`/`al_publish` resolve through `compatibility.md` and operate on the current project or whole workspace when all-project scope is available
    - Run tests with the AL test capability (`al_run_tests`); there is no PowerShell fallback, BcContainerHelper is denied by the block hook

## Git Operations

- This benchmark never commits, branches, or pushes, and never opens a pull request. Leave every
  edit - test and fix alike - as unstaged changes in the working tree; the harness diffs the
  working tree afterward.
- Use `git status` / `git diff` only to inspect what has changed so far; never use a write git
  command (`git add`, `git commit`, `git push`, `git checkout -b`, ...).

## Task Tracking

Use task management to track your progress:

- Create tasks for each phase
- Update status as you progress (in_progress, completed)
- This helps the user see what you're doing

## Best Practices

### Code Quality

- Follow existing code style and conventions
- Keep changes minimal and focused
- Add comments for non-obvious logic
- Do not add ticket-reference comments in code - there is no bug ID or PR to link the change to

### Testing

- Add the regression test that reproduces the bug - a reproducing test is always required in
  this benchmark
- Cover edge cases discovered during investigation
- Follow BC testing patterns and conventions
- Ensure tests are clear and maintainable

### Communication

- Be transparent about your analysis and decisions
- Present clear reasoning for the fix approach
- Highlight any risks or trade-offs
