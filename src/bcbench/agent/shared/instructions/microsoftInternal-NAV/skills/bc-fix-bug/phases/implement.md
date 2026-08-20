<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Fix Implement

Implements and validates the bug fix with a self-correcting loop until all tests pass (Phase 3), or -
when no AL tooling is attached (static mode) - implements the fix and validates it by inspection. A
reproducing test is always required in this benchmark.

## Input (from orchestrator prompt)

- `plan_bug_id` - numeric bug ID
- `plan_bug_title` - bug title
- `plan_content` - full plan body (root cause, fix, affected files, acceptance criteria)
- `progress_file` - absolute path to progress.md
- `temp_dir` - the state folder (`<os-temp>/bc-fix-bug/`), wiped at the start of each run
- `al_mode` - `executed` or `static` (`compatibility.md` → "AL tooling modes"). Re-detect it
  yourself if it is absent from the prompt; never assume `executed`.

## Rules & Output Guidelines

Read and follow `shared-rules.md` before proceeding.

## Phase 3: Implement Fix

### Step 0: Verify TDD Baseline Precondition

> **🚨 HARD GATE (shared-rules Rule 10). Do this BEFORE editing any product/source code. 🚨**

1. Read the baseline state file: `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json`.
2. The fix may proceed **only if** that file exists and reports `"baselineEstablished": true`.
3. Read `"mode"` from the same file and carry it through this phase (`compatibility.md` → "AL
   tooling modes"). It decides what "confirmed" required and what this phase must do:
   - `"executed"` - the baseline test was run and failed for the bug's reason. Run the fix loop
     below as written.
   - `"static"` - no AL tooling in this run. `<temp-dir>/bc-static-baseline-<plan_bug_id>.md` must
     also exist and name the offending `file:line` and the assertion it violates; treat its absence
     exactly like a missing state file. Skip steps c, d and e of the fix loop and follow step s.
4. **If the file is missing, unreadable, or `baselineEstablished` is not `true` (or, in static mode,
   the red argument is missing):**
   - Do **NOT** create or edit any product/source application code.
   - **Write progress.md - Milestone (implement-blocked):** append to activity_log
     `- [<now>] **implement-blocked**: TDD barrier not satisfied - baseline not confirmed; refusing to edit product code` and write `progress_file` with Status=`failed`. (Follow Rule 8.)
   - Report to the orchestrator that the baseline gate is not satisfied and **STOP**. The fix cannot
     begin until Phase 2 has produced a confirmed baseline.
5. If the gate is satisfied, display `✅ TDD baseline gate satisfied (<executed: baseline is red | static: red argument recorded>)` and proceed.

### Fix Loop (Self-Correcting Loop - Max 5 Iterations)

**Self-correcting iterations (up to 5):** repeat until tests pass. See Rules 1-2. In static mode
there are no test results to correct against, so the loop runs once (twice only to repair a defect
the static check found) - see Rule 2a.

1. **Initialize Iteration State**
    - **Use temp directory for state files** (avoid git-tracked folders)
    - Use `temp_dir` from the input prompt as the temp directory.
    - Create iteration state file: `<temp-dir>/bc-swe-iteration-state-<plan_bug_id>.json`
    - Initialize with (`mode` is the mode read at Step 0; `maxIterations` is 5 in executed mode and
      2 in static mode):
      ```json
      {
        "bugId": "<plan_bug_id>",
        "mode": "executed",
        "currentIteration": 0,
        "maxIterations": 5,
        "testsPassing": false,
        "iterationHistory": []
      }
      ```
    - This file persists state between iterations

2. **Implement Fix with Self-Correcting Iterations**
    - **Repeat this phase until the tests pass or the max iteration count is reached**

      **Each Iteration:**

      a. **Load Iteration State**
         - **Display**: `**=== FIX ITERATION <N> START ===**`
         - Read `<temp-dir>/bc-swe-iteration-state-<plan_bug_id>.json`
         - The temp folder is cleaned at the start of each run, so on the first iteration this file
           does not exist: initialize state (iteration 0)
         - On later iterations the file exists from an earlier iteration of this same run:
           - Check `currentIteration` value
           - Load previous iteration history
         - Increment `currentIteration`
         - **Write progress.md - Milestone 5 (fix-iteration-N-start):**
           Append to activity_log: `- [<now>] **fix-iteration-<currentIteration>-start**: Starting fix iteration <currentIteration>`
           Write `progress_file` with Status=`in-progress`. (Follow Rule 8. N is 1-based, incremented each time step a runs.)
         - If iteration > 1:
           - Review previous iteration history from state file
           - Check git diff to see what was already tried
           - Read previous test output: `<temp-dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N-1>.txt`
           - Identify patterns in failures and what to adjust
         - If iteration 1:
           - This is the first attempt, implement the plan from the input prompt
         - Update state file with current iteration number
         - Save diagnostic log: `<temp-dir>/bc-fix-diagnostic-<plan_bug_id>-iter-<N>.log`

      b. **Implement/Adjust Fix**
         - If iteration 1: Implement the fix based on the plan from the input prompt
         - If iteration 2+: Analyze test failures from state and adjust the fix
         - Make targeted changes to the identified files
         - Follow AL best practices:
           - Proper error handling
           - Clear variable naming
           - Appropriate comments for complex logic
           - Respect existing code style
         - Keep changes minimal and focused
         - Do NOT add comments referencing the bug ticket or issue ID in the code
         - Update state file:
           ```json
           {
             "iteration": N,
             "changes": ["File1.al:line123", "File2.al:line456"],
             "reasoning": "What was changed and why based on previous failures"
           }
           ```

      c. **Compile the Modified App** (executed mode only - in static mode skip to step s)
         - Display: "Compiling (iteration <N>)..."
         - Build with the AL build capability resolved through `compatibility.md` (all-project scope when available) to compile all modified projects (main app, test app) - see shared-rules Rule 2.
         - If the build fails: inspect details with the AL diagnostics capability, or parse build output if that capability is not advertised; fix errors and rebuild (doesn't count as new iteration)
         - Don't show verbose compiler output unless needed for debugging
         - If success: Display: "Compiled successfully"
         - Update state: `"compileStatus": "success"` or `"failed"` (silent)

         **→ Continue to next step (Rule 1)**

      d. **Publish the Modified App** (executed mode only - in static mode skip to step s)
         - Display: "Publishing main app (iteration <N>)..."
         - Publish with the AL publish capability resolved through `compatibility.md` (non-debug publish and dependency-chain publish when supported) - see shared-rules Rule 2.
         - The AL publish capability deploys the dependency chain when supported so dependent apps (like the test app) are reinstalled
         - **CRITICAL - then re-publish the built test app, explicitly and last.** Read `testApp.path` from `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json` (baseline step d saved it) and publish that artifact as its own publish call. The dependency-chain publish above can reinstall the container's *stock* copy of the test app over the one Phase 2 built, which silently removes the new test codeunit and makes every later test run execute old code. This is not detectable from version numbers - stock and locally built apps normally share the same app ID and version - so always re-publish rather than trying to detect it.
         - If `testApp.path` is missing from the state file, rebuild the test project and use the artifact path the build capability returns. Do not search the filesystem for `.app` files.
         - **Don't show verbose publish output**
         - If successful: Display: "Published successfully"
         - Update state: `"publishStatus": "success"` or `"failed"` (silent)

         **→ Continue to next step (Rule 1)**

      e. **Run Tests and Check for Completion (loop exit point)** (executed mode only - in static
         mode skip to step s)
         - Display: "Running tests (iteration <N>)..."
         - Run the test codeunit with the AL test capability (`al_run_tests`) resolved through `compatibility.md`; set `codeunitId` to the integer test codeunit ID - see shared-rules Rule 2.
          - If `al_build` is advertised but no AL test tool is, the environment is broken: BcContainerHelper is denied by the block hook, so stop and report the failure rather than driving the container yourself.
         - Save full test output to: `<temp-dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N>.txt` (silent)
         - **This file is a hard postcondition of the iteration, not a convenience artifact.** Phase 4
           (Summary) reads it to report the final test result and quote pass/fail counts, so write it
           on every iteration - passing or failing - and then confirm it exists and is non-empty:

           ```powershell
           $testOutput = Join-Path $temp_dir "bc-swe-test-output-$plan_bug_id-iteration-<N>.txt"
           if (-not (Test-Path -LiteralPath $testOutput) -or (Get-Item -LiteralPath $testOutput).Length -eq 0) {
               throw "Test output artifact was not written: $testOutput"
           }
           ```

           If the write fails, retry it once from the captured output already in hand. If it still
           cannot be written, do NOT emit `ALL TESTS PASSING`: append
           `- [<now>] **implement-blocked**: test output artifact could not be written for iteration <N>`
           to the activity log, write `progress_file` with Status=`failed`, and STOP. A green run whose
           evidence was never persisted cannot be summarized, and Phase 4 has no way to tell it apart
           from a run that was never executed.
         - Record the absolute path in the iteration state file as `"testOutputPath"` so Phase 4 can
           resolve the most recent output without searching the filesystem.
         - Parse test results internally
         - **CRITICAL - Loop Exit Logic:**
           - **If ALL tests PASS:**
             1. **CRITICAL VALIDATION - Must pass ALL checks before outputting promise:**
                - All tests executed without infrastructure errors
                - ALL tests show PASSED status (not failed, not skipped)
                - No compilation errors occurred
                - No publish errors occurred
                - Test results were parsed correctly
                - Count of passed tests matches count of expected tests
                - The iteration's test output artifact exists and is non-empty
                  (`<temp-dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N>.txt`)
             2. Update state file: `"testsPassing": true` (silent)
             3. **Display to user:**
                ```
                All tests passing! (iteration <N> of 5)
                   - TestNegativeQuantityValidation: PASSED
                   - TestZeroQuantityValidation: PASSED
                   - Fix successful
                ```
             4. **Display**: `**=== FIX ITERATION <N> END ===**`
             5. **Leave the fix and its tests uncommitted.** Do not stage, commit, branch, or push -
                the harness diffs the working tree directly (SKILL.md: "Do not commit, branch, or
                push"). Confirm the change is visible in the working tree:

                ```powershell
                git status --porcelain
                git --no-pager diff --stat
                ```

                If neither command shows the expected fix/test files, the edit did not land where
                expected: append
                `- [<now>] **implement-blocked**: expected changes not found in the working tree` to
                the activity log, write `progress_file` with Status=`failed`, and STOP without
                emitting `ALL TESTS PASSING`.
             6. **Declare completion (ONLY if all validation checks passed and the changes are
                present in the working tree):**
                ```
                ALL TESTS PASSING
                ```
             - **Write progress.md - Milestone 6 (tests-passing):**
               Append to activity_log: `- [<now>] **tests-passing**: All tests pass in iteration <currentIteration>`
               Write `progress_file` with Status=`in-progress`. (Follow Rule 8.)
             7. Stop iterating; the fix is complete
             8. Return control to the orchestrator (which proceeds to Phase 4: Summary)
           - **If ANY tests FAIL:**
             1. Update state file with failure details (silent)
             2. Analyze failure messages internally
             3. **Display to user:**
                ```
                Iteration <N>: Tests still failing
                   - TestNegativeQuantityValidation: FAILED
                   - Error: Field validation missing
                   - Action: Adjusting fix approach
                ```
             4. **Display**: `**=== FIX ITERATION <N> END ===**`
             5. Do not declare completion (tests not passing)
             6. Continue to the next iteration
             7. The next iteration starts at step (a) and reads this state

      s. **Static Verification and Completion (loop exit point - static mode only, replaces c-e)**
         - Display: "Verifying fix statically (no AL tooling in this run)..."
         - Apply the inspection check of shared-rules Rule 2a to every file changed in this phase:
           re-read each one in full after the last edit and confirm what the compiler would have
           caught (declared variables, resolvable object/procedure/field names, `using` namespaces,
           no accidental signature change to a public procedure).
         - Write the green argument to `<temp-dir>/bc-static-verification-<plan_bug_id>.md`. It must:
           - restate the `file:line` the red argument blamed and show the edit that changes it,
           - walk the same path over the edited code and show why the failing assertion now holds,
           - confirm every other assertion in the new test still holds, and
           - name any existing caller of the changed procedure you inspected for regressions.
         - Record the absolute path in the iteration state file as `"staticVerificationPath"` so
           Phase 4 can resolve it without searching the filesystem.
         - **CRITICAL VALIDATION - all checks must pass before declaring completion:**
           - ✅ The inspection check found no unresolved name or missing declaration
           - ✅ The green argument addresses the exact `file:line` from the red argument
           - ✅ The fix is minimal and targets the root cause, not the assertion
           - ✅ No existing test was modified (`git --no-pager diff --stat`)
           - ✅ `<temp-dir>/bc-static-verification-<plan_bug_id>.md` exists and is non-empty
         - **Leave the fix and its tests uncommitted.** Confirm the changes are in the working tree:

           ```powershell
           git status --porcelain
           git --no-pager diff --stat
           ```

           If neither command shows the expected fix/test files, append
           `- [<now>] **implement-blocked**: expected changes not found in the working tree` to the
           activity log, write `progress_file` with Status=`failed`, and STOP.
         - **Display to user:**
           ```
           Fix implemented and verified statically (not executed)
              • Changed: <file>:<line> - <one-line description>
              • Test: <TestProcedureName> now satisfied by <one-line reason>
              • Not executed: no AL tooling in this run; the harness runs the tests
           ```
         - **Declare completion (ONLY if all validation checks passed)** using the static promise
           from shared-rules Rule 2a - never `ALL TESTS PASSING`, which asserts an execution that
           did not happen:
           ```
           FIX COMPLETE (STATIC - NOT EXECUTED)
           ```
         - **Write progress.md - Milestone 6 (fix-verified-statically):**
           Append to activity_log: `- [<now>] **fix-verified-statically**: fix implemented and statically verified in iteration <currentIteration> (not executed)`
           Write `progress_file` with Status=`in-progress`. (Follow Rule 8.)
         - Stop iterating and return control to the orchestrator (which proceeds to Phase 4: Summary).

         **→ Fix loop ends here in static mode**

      f. **Check Iteration Limit**
         - If currentIteration >= maxIterations (the value in the state file - 5 in executed mode, 2
           in static mode):
           - Report: "Reached maximum of <maxIterations> fix iterations"
           - List tests still failing with error messages
           - Provide summary of all attempts from iteration history
           - Do not declare completion (tests not passing)
           - Stop iterating at the max
           - **Write progress.md - Milestone 7 (fix-iterations-exhausted):**
             Append to activity_log: `- [<now>] **fix-iterations-exhausted**: max iterations reached, tests still failing`
             Write `progress_file` with Status=`failed`. (Follow Rule 8.)
           - **This run is always unattended - there is no user to ask.** Return a structured failure
             to the orchestrator: report that the fix could not be completed after 5 iterations,
             include the list of still-failing tests and the summary of attempts, and STOP. The
             `progress_file` (Status=`failed`) is the handoff signal; the orchestrator reads it and
             halts.

3. **Document Fix Iterations (Automatic via State File)**
    - All iterations tracked in `<temp-dir>/bc-swe-iteration-state-<plan_bug_id>.json`
    - Each iteration's changes are visible in the (uncommitted) working tree diff
    - Executed mode - test outputs saved per iteration: `<temp-dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N>.txt`
    - Static mode - green argument: `<temp-dir>/bc-static-verification-<plan_bug_id>.md`
    - Creates comprehensive audit trail of the fix process
    - State file contains complete iteration history for the Phase 4 summary
