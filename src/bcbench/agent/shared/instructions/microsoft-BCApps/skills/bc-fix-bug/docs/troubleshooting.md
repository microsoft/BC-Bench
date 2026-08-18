<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Troubleshooting

Reference for common errors during `bc-fix-bug` execution.

---

## Tests run against old code / test codeunit "not found" after a successful publish

**Symptom:** The build and publish both report success, but the test run behaves as if the change
was never applied - the fix has no effect, or the new test codeunit is reported as missing.

**Cause:** A dependency-chain publish reinstalled the container's **stock** copy of a dependent app
on top of the one you just built. Observed with Tests-ERM: publishing the modified Base Application
reinstalled the shipped Tests-ERM, dropping the newly added test codeunit. Version numbers do not
expose this, because both apps normally carry the same app ID and version.

**Fix:** Follow shared-rules Rule 2 - publish the locally built test app explicitly as the **last**
publish before every test run, using `testApp.path` from the baseline state file. Do not try to
detect the problem after the fact, and do not go looking for `.app` files on disk to diagnose it
(those searches are outside the granted directories and are denied).

This is the single most expensive failure mode in this workflow: never re-work the fix or the test
on the strength of a test run whose test app you did not publish yourself.

---

## `al_publish` hangs or times out

**Symptom:** The publish capability produces no result and the call eventually times out.

**Fix:** See shared-rules Rule 2 ("Publish timeout"). In short: the timed-out publish may have
succeeded, so probe once with `Get-BcContainerAppInfo` (the only BcContainerHelper cmdlet still
available) and retry the AL capability at most once. There is no `Publish-BcContainerApp`
fallback - it is denied by the block hook. If the retry also times out while the probe keeps
answering, the publish path - not the container - is unavailable: record
`publishStatus: "unverified-timeout"` in progress.md with Status=`failed`, and STOP.

**Prevention:** publish what you already built. Pass `skipBuild: true` together with the artifact
path from the preceding build (or `testApp.path`), so the publish call does not spend its budget
re-compiling the project first. On Base Application-scale projects that hidden rebuild is one way
to push the call past its deadline, but it is not the only one: in run 31736761775 the call passed
an already-built `appPath` and still ran the full 40 minutes, so a clean `skipBuild` publish is no
guarantee.

**Diagnosing a repeat:** the run itself never explains what the publish was waiting on. If the
container and AL MCP server logs are reachable from this session (`almcp.log`, the container's
Application event log, the container's docker log, and this run's own `publish-calls.jsonl`
journal), check them in order rather than re-reading the agent transcript - the transcript only
records that the call timed out:

1. `al_publish - Starting` in `almcp.log` with no matching `Completed`. The server logs a call's
   parameters only once it returns, so for these calls read `publish-calls.jsonl` instead to see
   what was actually asked for.
2. Whether `al_downloadsymbols` ran before the first publish. Without that warm-up the developer
   endpoint is unproven when the publish starts.
3. Whether the container's Application event log shows NAV activity during the call. Silence
   there means the request never reached the service; suspect the connection values the publish
   call itself was given rather than the container.

---

## AL0185 / missing symbols (DotNet type or app symbol not found)

**Symptom:** Compilation fails with errors like:
```
error AL0185: DotNet 'NavUserAccountHelper' is missing
error AL1022: ... could not be found in the package cache
```

**Cause:** The project's symbols are missing or stale in `.alpackages`.

**Fix:** Run the `al_downloadsymbols` tool, then rebuild with `al_build`. If the type lives in a namespace the file hasn't imported, add the corresponding `using <Namespace>;` instead of downloading symbols.

The BC container and AL MCP server are provisioned before this skill runs - do not reset or relaunch them.

---

## Environment / container not responding

**Symptom:** Builds or test runs fail because the BC container or AL MCP server is unavailable.

**Cause:** The environment is provisioned before this session starts; this section only applies if that setup did not complete.

**Fix:** Confirm the container is running (`docker ps` - the name is in `$env:BC_CONTAINER_NAME`) and that the `al_*` tools are available. If the environment is missing, report the failure rather than provisioning manually from this skill - this benchmark run does not include a step for you to bootstrap the container.

---

## Plan File Missing or Not Found

**Symptoms:**

- Error: `Plan file not found: <path>`

**Causes:**

- The plan file path is wrong or the file was deleted

**Solutions:**

1. Re-read `problem/README.md` and re-run Phase 1 to regenerate `<temp_dir>/plan.md`
2. Verify the plan file exists at `<temp_dir>/plan.md` (`<os-temp>/bc-fix-bug/plan.md`)

## Baseline Not Establishing

**Symptoms:**

- Phase 2 (baseline) loop continues past 5 iterations
- Tests keep passing when they should fail
- Tests fail with wrong error

**Causes:**

- Tests don't actually trigger the bug
- Test data setup incorrect
- Bug already fixed in codebase

**Solutions:**

1. Check test implementation matches bug scenario
2. Verify test data triggers the bug condition
3. Review test results to understand why it's not reproducing bug
4. Adjust test manually if needed

## Fix Loop Not Completing

**Symptoms:**

- Phase 3 (fix loop) reaches 5 iterations without passing
- Tests keep failing with same error
- Fix doesn't address root cause

**Causes:**

- Fix approach incorrect
- Missing dependencies or setup
- Side effects not considered

**Solutions:**

1. Review iteration history to see what was tried
2. Analyze test failure patterns
3. Reconsider fix approach
4. May need to restart with different strategy

## State Files Not Found

**Symptoms:**

- "State file not found" errors mid-loop
- Lost iteration history within a run

**Note:** This workflow does not resume across runs. The `%TEMP%\bc-fix-bug\` folder (which
holds every state file) is deleted and recreated at the start of every run, so each invocation starts
from a clean slate. State files only carry iteration history within a single run's loop.

**Causes:**

- State folder cleaned mid-run
- Different user session
- State files manually deleted

**Solutions:**

1. Re-run the workflow from the beginning
2. State files live under `%TEMP%\bc-fix-bug\`
3. Check: `%TEMP%\bc-fix-bug\bc-test-baseline-state-BENCH.json`
4. Check: `%TEMP%\bc-fix-bug\bc-swe-iteration-state-BENCH.json`
