# Troubleshooting

Build, publish, and test problems, and what each one means. Read `rules.md` first: compile errors
and failing tests are loop feedback, everything below that describes a stuck tool is infrastructure
and is terminal (Rule 15).

---

## No AL tool is advertised

Not a failure. The AL tools are optional in this environment, so the task is code-change-only:
implement the fix by reading and reasoning about the code, and say in your report that it was not
built. Never drive the container yourself to compensate (Rule 8).

---

## `AL0185` / `AL1022` - missing symbols

The project's symbols are missing or stale in `.alpackages`. Call `al_downloadsymbols` once, then
rebuild. If it fails a second time, that is terminal.

If the type lives in a namespace the file has not imported, add `using <Namespace>;` instead - a
missing `using` is a code error and no symbol download will fix it.

---

## Publish timed out

A timeout does not prove the publish stopped or rolled back. Publishing can take many minutes,
especially for BaseApp, and interruption can leave the app unpublished and dependent apps
uninstalled.

**Do not retry the publish.** A successful `al_downloadsymbols` call only shows that the developer
endpoint responds; it does not prove the previous publish finished or its state is safe.

Stop, leave the fix in the working tree, and report that the publishing outcome is unknown. Do not
run tests against that uncertain deployment or attempt to repair it by changing versions or driving
the container yourself.

---

## Publish failed

`al_publish` reports every cause with the same generic text plus a boilerplate list of possible
causes. It is not a description of what happened.

**Do not treat it as a hint and do not permute the call.** Not a different `appPath`, not a rebuilt
package, not a different version, not a different dependency setting. Treat this as terminal
infrastructure feedback: do not retry. Stop and report - the fix in the working tree is still
collected.

---

## Tests run against old code, or a test codeunit is "not found" after a successful publish

A dependency-chain publish reinstalled the container's stock copy of a dependent app over the one
you built, so the test run executed shipped code. Version numbers do not expose this: stock and
locally built apps normally share the same app ID and version.

Re-publish the app the tests live in explicitly, as the last publish before the test run, using the
artifact path its build returned. Do not go looking for `.app` files on disk (Rule 12), and never
re-work a fix on the strength of a test run whose app you did not publish yourself.

---

## The fix loop keeps failing the same way

Five iterations of the same failure means the approach is wrong, not incomplete. Re-read the root
cause: the usual causes are fixing a symptom downstream of the real defect, a missing setup or
dependency in the code path, or a side effect that was not considered. Stop at iteration 5, leave
the best version of the fix in place, and report what still fails.
