<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Fix Baseline

Creates AL tests via test-implementor and establishes a failing baseline that reproduces the bug (Phase 2).

## Input (from orchestrator prompt)

- `plan_bug_id` - numeric bug ID
- `plan_bug_title` - bug title
- `plan_content` - full plan body (root cause, fix, affected files, acceptance criteria)
- `progress_file` - absolute path to progress.md
- `temp_dir` - the state folder (`<os-temp>/bc-fix-bug/`), wiped at the start of each run

## Rules & Output Guidelines

Read and follow `shared-rules.md` before proceeding.

This phase creates test code only. It must not create or edit product/source application code - the
fix belongs to Phase 3 (shared-rules Rule 10). The goal is a test that fails because the bug is
present.

## Phase 2: Create Tests and Establish Baseline

1. **Establish Test Baseline (iterate up to 5 times)**

   **CRITICAL: Iterate - up to 5 times - to create tests that properly reproduce the bug before any fix is attempted.**

   ```
   Step a: Load State          ← Start here
   Step b: Create/Adjust Tests ← Continue (don't stop)
   Step b1: Verify Placement   ← → continue
   Step c: Compile Test App    ← → continue
   Step d: Publish Test App    ← → continue
   Step e: Run Tests           ← End here (check if baseline established)
   ```

   **Initialize Baseline State:**
   - **Use temp directory for state files** (avoid git-tracked folders)
   - Use `temp_dir` from the input prompt as the temp directory.
   - Create baseline state file: `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json`
   - Initialize with:
     ```json
     {
       "bugId": "<plan_bug_id>",
       "currentIteration": 0,
       "maxIterations": 5,
       "baselineEstablished": false,
       "iterationHistory": []
     }
     ```

   **Baseline Loop (Repeat until tests fail properly or max 5 iterations):**

   a. **Load Iteration State**
      - **Display**: `**=== BASELINE ITERATION <N> START ===**`
      - Read `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json`
      - The temp folder is cleaned at the start of each run, so on the first iteration this file
        does not exist: initialize state (iteration 0)
      - On later iterations the file exists from an earlier iteration of this same run:
        - Check `currentIteration` value
        - Load previous iteration history
      - Increment `currentIteration`
      - If iteration > 1:
        - Review previous iteration history
        - Read previous test output: `<temp-dir>/bc-test-baseline-output-<plan_bug_id>-iteration-<N-1>.txt`
        - Identify why tests didn't fail correctly
      - Update state file with current iteration
      - Save diagnostic log: `<temp-dir>/bc-baseline-diagnostic-<plan_bug_id>-iter-<N>.log`
      - **Write progress.md - Milestone (baseline-iteration-N-start):**
        Append to activity_log: `- [<now>] **baseline-iteration-<currentIteration>-start**: Starting baseline iteration <currentIteration>`
        Write `progress_file` with Status=`in-progress`. (Follow Rule 8.)

   b. **Create or Adjust Test Implementation**
      - If iteration 1:
        - Display: "🧪 Creating tests..."
        - Read `phases/test-implementor.md` and follow it inline to
          implement the tests, or dispatch it through the sub-agent capability from
          `compatibility.md` if that capability is advertised. Use this
          task context:
          ```
          Create test case(s) for issue #<id>: <description>.

          ## Bug Fix Plan
          <plan_content from the input prompt>

          Based on the plan's testing section, create tests that:
          - Reproduce the bug scenario described in the plan
          - Will validate the fix once implemented
          - Follow BC test patterns

          ## Test placement (mandatory)

          Add the [Test] procedure to an EXISTING test codeunit. Run the searches in
          <test_placement> in test-implementor.md before you write any test code. A new test
          codeunit is a last resort, allowed only when those searches surface no suite that can
          host the test, and it must name the candidates examined and why each was rejected.
          Return the `Test placement:` line as the first line of your reply.
          ```
          Only write the test code here. Do NOT compile, publish, or run tests - steps c–e below handle that.
      - If iteration 2+:
        - Analyze why previous test didn't fail properly
        - Adjust test implementation directly using Edit tool:
          - Fix test logic if it passed unexpectedly
          - Adjust test data if bug wasn't triggered
          - Add missing setup steps if environment wasn't correct
          - Fix test errors if it failed for wrong reasons
        - Document adjustments in state file

   b1. **Verify Test Placement (gate)**

      Judge the working tree, not the reported decision. Run this on every iteration.

      - List the AL files added so far in this run: `git status --porcelain -- "*.al"` (look for
        `??` untracked entries; this run never commits, so every new file is still untracked).
      - If none of them contains `Subtype = Test;`, the tests went into an existing suite. Continue.
      - Otherwise list the suites that already exist in that file's test app (nearest ancestor
        `app.json`):
        `git grep -l -i -E "Subtype[[:space:]]*=[[:space:]]*Test[[:space:]]*;" -- "<app-root>/*.al"`
      - If that list is non-empty, re-dispatch step b **once**, quoting those exact paths, and
        require the test to be moved into the best match unless the writer names the candidates it
        examined and why none can host it. Record the outcome in `progress_file`, then continue.

      **→ Continue to next step (Rule 1)**

   c. **Compile Test App**
      - Display: "🛠️ Compiling test app..."
      - Build with the AL build capability resolved through `compatibility.md` (all-project scope when available) - see shared-rules Rule 2
      - If success: Display "✅ Test app compiled"
      - If failure: Display "❌ Compilation failed: <error-summary>" (inspect details with the AL diagnostics capability, or parse build output if that capability is not advertised), fix, retry
      - **Don't show verbose compiler output unless there's an error**

      **→ Continue to next step (Rule 1)**

   d. **Publish Test App**
      - Display: "📦 Publishing test app..."
      - Publish with the AL publish capability resolved through `compatibility.md` (non-debug publish when supported) - see shared-rules Rule 2
      - If success: Display "✅ Test app published"
      - **CRITICAL**: Save test app metadata to state file for the implement phase (fix loop):
        - Read test app's app.json to get: name, publisher, version
        - Store in state file: `"testApp": {"name": "...", "publisher": "...", "version": "...", "path": "..."}`
        - This will be needed by the implement phase to uninstall/reinstall the test app
      - **Don't show verbose publish output**

      **→ Continue to next step (Rule 1)**

   e. **Run Tests and Analyze Results (Baseline Loop Exit Point)**
      - Display: "🧪 Running tests (iteration <N>)..."
      - Run the tests using the AL test capability (`al_run_tests`) from `compatibility.md`. There is no PowerShell fallback: if no AL test tool is advertised, stop and report the failure (shared-rules Rule 2).
      - Save full output to: `<temp-dir>/bc-test-baseline-output-<plan_bug_id>-iteration-<N>.txt` (silent)
      - **Parse results, show summary only:**
      - **CRITICAL - Baseline Loop Exit Logic:**

        **If tests FAIL with bug-related error (EXPECTED):**
        1. Verify the failure message matches the bug symptoms
        2. **CRITICAL VALIDATION - Must pass ALL checks before outputting promise:**
           - ✅ Tests executed without errors
           - ✅ Test failed (not passed, not skipped)
           - ✅ Error message matches expected bug symptoms
           - ✅ Error is related to the bug being fixed
           - ✅ Not a test infrastructure error (missing handlers, table relations, etc.)
        3. Update state: `"baselineEstablished": true`
        4. **Display to user:**
           ```
           ✅ Baseline established (iteration <N> of 5)
              • Test: TestNegativeQuantityValidation
              • Result: FAILED (as expected)
              • Error: "Quantity must not be negative"
              • Conclusion: Test successfully reproduces the bug
           ```
        5. **Display**: `**=== BASELINE ITERATION <N> END ===**`
        6. **Declare the baseline established (ONLY if all validation checks passed)** and stop iterating:
           ```
           TEST BASELINE ESTABLISHED
           ```

   **Write progress.md - Milestone 3 (baseline-established):**
   Append to activity_log: `- [<now>] **baseline-established**: <test-name> failed as expected in iteration <currentIteration>`
   Write `progress_file` with Status=`in-progress`. (Follow Rule 8.)

        7. Baseline loop ends successfully; return to the orchestrator

        **If tests PASS (UNEXPECTED - bug not reproduced):**
        1. Update state with analysis (silent)
        2. **Display to user:**
           ```
           ⚠️ Iteration <N>: Tests passed (unexpected)
              • Test should FAIL to reproduce bug
              • Possible cause: Test doesn't trigger bug condition
              • Action: Adjusting test to reproduce bug properly
           ```
        3. Do not declare the baseline established
        4. Continue to the next iteration with the same goal
        5. Next iteration adjusts test to reproduce bug

        **If tests FAIL for wrong reason (ERROR - test broken):**
        1. Update state with error analysis (silent)
        2. **Display to user:**
           ```
           ⚠️ Iteration <N>: Test failed (wrong error)
              • Expected error: "Quantity must not be negative"
              • Actual error: "Table relation validation failed"
              • Action: Fixing test implementation
           ```
        3. Do not declare the baseline established
        4. Continue to the next iteration with the same goal
        5. Next iteration fixes test implementation

   f. **Check Iteration Limit**
      - If currentIteration >= maxIterations (5):
        - Report: "Reached maximum of 5 baseline iterations"
        - Provide summary of all attempts
        - Do not declare the baseline established
        - Stop iterating

        **Write progress.md - Milestone 4 (baseline-failed):**
        Append to activity_log: `- [<now>] **baseline-failed**: max iterations reached`
        Write `progress_file` with Status=`failed`. (Follow Rule 8.)

        **This run is always unattended - there is no user to ask.** Return a structured failure to
        the orchestrator: report that the baseline could not be established after 5 iterations,
        include the summary of attempts, and STOP. The `progress_file` (Status=`failed`) is the
        handoff signal; the orchestrator reads it and halts.

   **Document Baseline Iterations:**
   - All attempts tracked in `<temp-dir>/bc-test-baseline-state-<plan_bug_id>.json`
   - Test outputs per iteration: `<temp-dir>/bc-test-baseline-output-<plan_bug_id>-iteration-<N>.txt`
   - Final baseline evidence ready for the implement phase (the fix loop)
