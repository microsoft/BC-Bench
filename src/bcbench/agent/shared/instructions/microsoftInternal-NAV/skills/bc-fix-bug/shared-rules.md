<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Shared Rules for the bc-fix-bug Workflow

These rules apply to all phases of the bug fix workflow. Resolve every tool through
`compatibility.md`.

## Rules

1. Complete all steps in each loop iteration without pausing (baseline a to e, fix loop a to f).
   Never stop after compile or publish. One narrow exception is defined below and nowhere else: an
   unrecoverable AL tool failure (Rule 2, "Publish timeout"). It stops *between* iterations, never
   half-way through one. In static mode the compile, publish and test steps do not exist at all, so
   each loop is a single uninterrupted pass through the steps that remain (Rule 2a).
2. **Executed mode only** (`compatibility.md` → "AL tooling modes"; in static mode this whole rule
   is inapplicable - follow Rule 2a instead). Use the AL tools and the provided BC container for
   compile, publish, and test. Never use raw
   `alc.exe`, `msbuild`, `Publish-NAVApp`, or `Import-NAVApp`, and never bootstrap the environment
   yourself. The container and AL MCP server are provisioned before this skill runs.
   - Build: the AL build capability. Inspect failures with the AL diagnostics capability. If a
     build fails with missing-symbol errors, download symbols once, then rebuild.
   - Publish: the AL publish capability. **When tests are required, always publish the locally built
     test app LAST, from its saved artifact path, as its own explicit publish call** (baseline step d
     stores it as `testApp.path` in the baseline state file). A dependency-chain publish of the main
     app can reinstall the container's *stock* copy of a dependent app on top of the one you just
     built - observed on Tests-ERM, where the shipped app replaced the freshly built one, the new
     test codeunit vanished, and every later run silently executed old code. Publishing the built
     test app last makes this deterministic; do not rely on noticing it afterwards. Version numbers
     do not disambiguate here, because the stock and locally built apps usually carry the same app ID
     and version.
   - Before concluding "the fix did not work" in a test-required run, confirm the last publish of the
     test app was the explicit one above. A test result from an unverified deployment is not evidence.
   - Build artifacts: take the `.app` output path from the build capability's own result, or from
     `testApp.path` in the state file. **Never search the filesystem for `.app` files**
     (`Get-ChildItem -Recurse` over `%LOCALAPPDATA%`, `C:\Windows\Temp`, user profile folders,
     ...). Only the repository working directory and `%TEMP%` are granted, so those searches are
     denied outright and the time is wasted; rebuild to re-obtain the path instead.
   - Publish timeout: if the AL publish capability times out, do not assume it failed - it may
     still have completed. Query the container's installed apps once
     (`Get-BcContainerAppInfo -containerName $env:BC_CONTAINER_NAME`), then act on what it tells
     you:
     - The probe itself fails, hangs, or reports no container: the container is gone, not slow.
       Stop now rather than spending another publish timeout on it.
     - The probe answers: **call `al_downloadsymbols` once before retrying the publish.** It
       exercises the same developer endpoint in seconds instead of tens of minutes, so it tells
       you whether a retry has any chance. If `al_downloadsymbols` hangs or fails, the endpoint
       is dead: stop and report the failure - do **not** spend a second full publish timeout
       confirming it. Only if it succeeds, retry the AL publish capability **once**, whatever
       the app list showed. A present app does **not** prove your build landed - the stock and
       locally built apps carry the same ID and version, so the entry you see may be the shipped
       one (this is exactly the Tests-ERM failure described above). Never read "installed" as
       "published"; re-publish and let the tool confirm.

     `Get-BcContainerAppInfo` is the single BcContainerHelper cmdlet still available, because it
     is read-only; there is no publish, compile or test fallback behind it (see Rule 2). If the
     retry also times out, the container is unrecoverable for this run: this is the sanctioned
     exception to Rule 1 - stop between iterations, record the failure in `progress_file`, and
     STOP. Do not loop, and do not look for a way around the publish tool.
   - Run tests: the AL test capability (`al_run_tests`). It works in both hosts. There is no
     PowerShell fallback - if `al_build` is advertised but no AL test tool is, the environment is
     broken: stop and report the failure rather than driving the container yourself. (No AL tool at
     all is static mode, not a broken environment - see Rule 2a.) Parse the output to decide next
     steps.
   - Connection values come from the environment, not from guesswork. The workflow exports
     `$env:BC_SERVER_URL`, `$env:BC_SERVER_INSTANCE`, `$env:BC_SERVER_DEV_PORT`,
     `$env:BC_SERVER_USERNAME` and `$env:BC_SERVER_PASSWORD` once the container exists. Pass them
     on **every** `al_publish`/`al_run_tests` call: `server` = `$env:BC_SERVER_URL`,
     `serverInstance` = `$env:BC_SERVER_INSTANCE`, `port` = `$env:BC_SERVER_DEV_PORT`,
     `authentication` = `UserPassword`. The tool's own defaults (no server, Windows
     authentication) never reach the container. Never assume the instance equals the Windows
     service suffix. Only when one of these variables is genuinely absent, fall back to reading
     the target service's `CustomSettings.config`:

     ```powershell
     $svc = Get-CimInstance Win32_Service -Filter "Name='MicrosoftDynamicsNavServer$<suffix>'"
     $exe = ($svc.PathName -replace '^"','' -split '"')[0]
     $cfg = Get-ChildItem (Split-Path $exe -Parent) -Recurse -Filter CustomSettings.config | Select-Object -First 1
     ([xml](Get-Content $cfg.FullName)).appSettings.add |
       Where-Object { $_.key -eq 'ServerInstance' } | ForEach-Object { $_.value }
     ```

     If `al_publish`/`al_run_tests` returns 404 or "publish failed", re-resolve (the instance name
     is wrong) instead of retrying the same value.
   - **Establish the server session before the first publish.** Call `al_downloadsymbols` once,
     with the connection values above, after the first successful `al_build` and **before** the
     first `al_publish` of the run. It is the cheap call that proves the developer endpoint is
     reachable and the credentials work; a publish that is the first thing to touch the endpoint
     can stall for the whole tool timeout instead of failing. If `al_downloadsymbols` itself
     hangs or fails, the environment is broken: stop and report the failure rather than spending
     publish timeouts discovering the same thing.
   - Record what you are about to publish. Immediately before each `al_publish`, append one JSON
     line - timestamp, `appPath`, `server`, `serverInstance`, `port`, `authentication`,
     `skipBuild` - to `publish-calls.jsonl` in the per-bug state folder (`temp_dir`). The AL MCP
     server logs a call's parameters only *after* it returns, so a publish that never returns
     otherwise leaves no record of what it was asked to do.
2a. **Static mode only** (`compatibility.md` → "AL tooling modes"). No AL tool is advertised, so
   nothing is compiled, published, or executed in this run. This is a supported configuration, not
   a failure: the harness re-runs the red/green checks against the gold patch afterwards and scores
   the run identically. Replace each executed step with its static counterpart:
   - **Instead of compiling**, re-read every file you changed, in full, after the last edit. Check
     by inspection what the compiler would have caught: every object, procedure, field and variable
     you reference exists and is spelled as declared; every variable is declared; the test codeunit
     carries `Subtype = Test;`; every UI the test touches has a matching handler attribute; new
     `using` namespaces are imported. Compare against a neighbouring test in the same codeunit
     rather than trusting recall.
   - **Instead of running tests for the baseline**, write the red argument: trace, in prose, the
     exact product-code path the new test drives, cite the `file:line` of the buggy statement, and
     state which assertion of the new test that statement violates today. Save it to
     `<temp_dir>/bc-static-baseline-<plan_bug_id>.md`. If you cannot name that line and that
     assertion, the test does not demonstrably reproduce the bug - revise the test, not the
     argument.
   - **Instead of running tests after the fix**, write the green argument: walk the same path over
     the edited code, show why the assertion now holds, and confirm no other assertion in the test
     regressed. Save it to `<temp_dir>/bc-static-verification-<plan_bug_id>.md`.
   - **Never claim execution you did not perform.** Do not write "tests passed", "tests failed",
     "compiled successfully", "published", `TEST BASELINE ESTABLISHED`, or `ALL TESTS PASSING` in
     static mode. Use the static promises instead: `TEST BASELINE ESTABLISHED (STATIC)` at the end
     of Phase 2 and `FIX COMPLETE (STATIC - NOT EXECUTED)` at the end of Phase 3. A run that fakes
     an executed result is worse than one that reports honestly, because it cannot be told apart
     from a real green run.
   - **Do not improvise an execution path.** `alc.exe`, `msbuild` and BcContainerHelper stay denied
     (Rule 2), and the harness prompt explicitly tells the agent not to build or run tests when the
     AL tools are absent. Attempting it wastes the budget and invalidates the shared container.
   - Static loops do not iterate on test results, because there are none. Make one pass, run the
     static checks above, and take a second pass only to repair a defect those checks found.
3. Only report a phase complete after all of its validation checks pass.
4. Parse command outputs silently; show short progress summaries, not raw output.
5. This run is always unattended: proceed through every phase without pausing for approval. There
   is no approval gate, no `--yes` flag, and no `--plan-file` entry point in this benchmark.
6. Compile every modified project (main app, test app) - executed mode only; in static mode apply
   the inspection check of Rule 2a to every modified project instead.
7. Keep state files in the per-bug state folder (passed as `temp_dir`), never in git-tracked folders.
8. Write progress.md at each milestone: overwrite the file with the current header followed by the
   accumulated activity log with the new entry appended. On write failure, warn and continue.
   - The header keeps the shape and the full field set of `templates/progress-template.md`: a
     `# Bugfix: <title>` heading, then `> `-quoted `Status`, `Bug-ID`, `Bug-Title`, `Source`,
     `Repo`, `Branch`, `PR-Link`, `Last-Updated`, `Attempt`. Never drop a field, and never invent a
     different header layout - unattended callers parse this file. This benchmark never creates a
     branch or a pull request, so `Branch` and `PR-Link` stay blank; leave them, don't remove them.
   - "Accumulated" is literal: read the existing file first and carry **every** prior activity-log
     entry forward. A phase that rewrites the file from a blank template destroys the audit trail of
     the phases before it, which is the only record of what actually happened on a runner that is
     about to be discarded.
   - Every `<now>` is the real current UTC time, taken from the clock
     (`(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')`), never estimated, rounded to
     a whole minute, or copied from a neighbouring entry. A timestamp in the future is proof the
     log was invented rather than recorded.
   - Status takes exactly one of four values: `not-started`, `in-progress`, `failed`, or
     `completed`. Only Phase 4 (Summary) writes `completed`, and only once Phase 3 has reported
     success - `ALL TESTS PASSING` in executed mode, `FIX COMPLETE (STATIC - NOT EXECUTED)` in
     static mode. Unattended callers gate on this field, so a successful run that never
     reaches `completed` is indistinguishable from a failed one.
9. No ticket-reference comments in code. There is no bug ID, commit, or pull request to link the
   change to - the fix is judged by its diff and the passing test alone.
10. **TDD barrier (test-first invariant).** A reproducing test is always required in this
    benchmark - there is no no-test path. Product/source application code MUST NOT be created or
    edited until the Phase 2 baseline is confirmed. The baseline state file
    `<temp-dir>/bc-test-baseline-state-<bug_id>.json` must exist and report
    `"baselineEstablished": true` before any fix edit. Phase 2 writes test code only; Phase 3
    verifies this gate at its Step 0 and STOPs if it is not satisfied. What "confirmed" means
    depends on the mode recorded as `"mode"` in that same file:
    - `"executed"` - the test was run and failed for the bug's reason (baseline step e).
    - `"static"` - the red argument of Rule 2a exists at
      `<temp-dir>/bc-static-baseline-<bug_id>.md` and names the offending `file:line` and the
      assertion it violates.

    The barrier is about ordering, and it holds in both modes: the harness scores the test half of
    the diff against the *unfixed* code, so a test written after the fix - or written to match the
    fix rather than the bug - is exactly what this rule exists to prevent.

## Output Guidelines

Provide clear progress indicators, natural-language summaries of what was found and done, the key
information (bug summary, root cause, files affected, validation results), and decision points
("Baseline established", "All tests passing").

Do not show raw shell outputs, authentication details, verbose tool output (unless there is an
error), or long JSON or logs. Save verbose output to `<temp-dir>/bc-fix-bug-debug-<bug_id>.log`.
