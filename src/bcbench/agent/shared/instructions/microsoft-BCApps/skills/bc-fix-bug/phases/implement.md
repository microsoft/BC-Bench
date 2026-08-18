<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Fix Implement

Implements and validates the bug fix. Test-required plans use a self-correcting loop until all tests
pass; no-test plans build and publish without creating or executing tests (Phase 3).

## Input (from orchestrator prompt)

- `plan_bug_id` - numeric bug ID
- `plan_bug_title` - bug title
- `plan_content` - full plan body (root cause, fix, affected files, acceptance criteria)
- `progress_file` - absolute path to progress.md
- `temp_dir` - the state folder (`<os-temp>/bc-fix-bug/`), wiped at the start of each run
- `skip_tests` - `true` or `false` (default: `false`). The orchestrator derives it from the approved
  plan's `tests-required` value. When `true`, implement, build, and publish but skip all test creation
  and execution.

## Rules & Output Guidelines

Read and follow `shared-rules.md` before proceeding.

## Phase 3: Implement Fix

### Step 0: Verify TDD Baseline Precondition (normal mode only)

> **🚨 HARD GATE (shared-rules Rule 10). Do this BEFORE editing any product/source code. 🚨**

**If `skip_tests == false`:**

1. Read the baseline state file: `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json`.
2. The fix may proceed **only if** that file exists and reports `"baselineEstablished": true`.
3. **If the file is missing, unreadable, or `baselineEstablished` is not `true`:**
   - Do **NOT** create or edit any product/source application code.
   - **Write progress.md - Milestone (implement-blocked):** append to activity_log
     `- [<now>] **implement-blocked**: TDD barrier not satisfied - baseline not confirmed red; refusing to edit product code` and write `progress_file` with Status=`failed`. (Follow Rule 8.)
   - Report to the orchestrator that the baseline gate is not satisfied and **STOP**. The fix cannot
     begin until Phase 2 has produced a failing (red) baseline test.
4. If the gate is satisfied, display `✅ TDD baseline gate satisfied (baseline is red)` and proceed.

**If `skip_tests == true`**: the approved plan states that tests are not applicable. The TDD barrier
does not apply; skip this step and proceed to the No-Test Validation Path below.

### No-Test Validation Path

**If `skip_tests == true`**, implement, build, and publish but skip all test creation and execution:

1. Implement the fix based on `plan_content` - make the targeted code changes to the identified files.
2. Follow AL best practices (proper error handling, clear naming, respect existing code style). Keep changes minimal and focused.
3. **Compile every modified project** with the AL build capability resolved through `compatibility.md` (all-project scope when available) - see shared-rules Rules 2 and 6. If compilation fails, inspect details with the AL diagnostics capability, or parse build output if that capability is not advertised; fix errors and retry.
4. **Publish the modified app** with the AL publish capability resolved through `compatibility.md` (non-debug publish when supported) - see shared-rules Rule 2. If publish fails, fix errors and retry.
5. Read the plan's `## Test Strategy` and write
   `<temp-dir>/bc-swe-iteration-state-<plan_bug_id>.json`:

   ```json
   {
    "bugId": "<plan_bug_id>",
    "testsRequired": false,
    "validationComplete": true,
    "buildStatus": "success",
    "publishStatus": "success",
    "validationApproach": "<the plan-specific manual or external validation approach>"
   }
   ```

   Write this state only after the build and publish both succeed. If the Test Strategy or its
   validation approach is missing, write `progress_file` with Status=`failed`, report the invalid
   plan to the orchestrator, and STOP.
6. Leave the fix uncommitted in the working tree - do not stage, commit, branch, or push
   (SKILL.md: "Do not commit, branch, or push").
7. **Write progress.md - Milestone (validation-complete):**
   Append to activity_log:
   `- [<now>] **validation-complete**: Tests not required by plan; build and publish succeeded; validation approach recorded`
   Write `progress_file` with Status=`in-progress`.
8. Report exactly: `NO-TEST VALIDATION COMPLETE`.
9. **Return to the orchestrator.** It proceeds to Phase 4 (Summary).

### Normal Mode Path (Self-Correcting Loop - Max 5 Iterations)

**Self-correcting iterations (up to 5):** repeat until tests pass. See Rules 1-2.

1. **Initialize Iteration State**
    - **Use temp directory for state files** (avoid git-tracked folders)
    - Use `temp_dir` from the input prompt as the temp directory.
    - Create iteration state file: `<temp-dir>/bc-swe-iteration-state-<plan_bug_id>.json`
    - Initialize with:
      ```json
      {
        "bugId": "<plan_bug_id>",
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

      c. **Compile the Modified App**
         - Display: "Compiling (iteration <N>)..."
         - Build with the AL build capability resolved through `compatibility.md` (all-project scope when available) to compile all modified projects (main app, test app) - see shared-rules Rule 2.
         - If the build fails: inspect details with the AL diagnostics capability, or parse build output if that capability is not advertised; fix errors and rebuild (doesn't count as new iteration)
         - Don't show verbose compiler output unless needed for debugging
         - If success: Display: "Compiled successfully"
         - Update state: `"compileStatus": "success"` or `"failed"` (silent)

         **→ Continue to next step (Rule 1)**

      d. **Publish the Modified App**
         - Display: "Publishing main app (iteration <N>)..."
         - Publish with the AL publish capability resolved through `compatibility.md` (non-debug publish and dependency-chain publish when supported) - see shared-rules Rule 2.
         - The AL publish capability deploys the dependency chain when supported so dependent apps (like the test app) are reinstalled
         - **CRITICAL - then re-publish the built test app, explicitly and last.** Read `testApp.path` from `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json` (baseline step d saved it) and publish that artifact as its own publish call. The dependency-chain publish above can reinstall the container's *stock* copy of the test app over the one Phase 2 built, which silently removes the new test codeunit and makes every later test run execute old code. This is not detectable from version numbers - stock and locally built apps normally share the same app ID and version - so always re-publish rather than trying to detect it.
         - If `testApp.path` is missing from the state file, rebuild the test project and use the artifact path the build capability returns. Do not search the filesystem for `.app` files.
         - **Don't show verbose publish output**
         - If successful: Display: "Published successfully"
         - Update state: `"publishStatus": "success"` or `"failed"` (silent)

         **→ Continue to next step (Rule 1)**

      e. **Run Tests and Check for Completion (loop exit point)**
         - Display: "Running tests (iteration <N>)..."
         - Run the test codeunit with the AL test capability (`al_run_tests`) resolved through `compatibility.md`; set `codeunitId` to the integer test codeunit ID - see shared-rules Rule 2.
          - If no AL test tool is advertised, the environment is broken: BcContainerHelper is denied by the block hook, so stop and report the failure rather than driving the container yourself.
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

      f. **Check Iteration Limit**
         - If currentIteration >= maxIterations (5):
           - Report: "Reached maximum of 5 fix iterations"
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
    - Test outputs saved per iteration: `<temp-dir>/bc-swe-test-output-<plan_bug_id>-iteration-<N>.txt`
    - Creates comprehensive audit trail of the fix process
    - State file contains complete iteration history for the Phase 4 summary
