# BC/AL Bug Fix Workflow

You investigate one bug in the checked-out repository, write a fix plan, implement it, and validate
it. Read `rules.md` before executing this workflow.

**Input**: the issue description and repository path extracted in Step 2 of `SKILL.md`.

---

## Phase 1: Investigate and Plan

### Step 1: Establish the root cause

Prefer symbol navigation over raw text search whenever an LSP is available in this session;
otherwise use `grep`, `glob`, and `view`. If an LSP call errors or no server is configured, fall
back to search and file reads for that query and continue.

> **Discover-then-pivot rule:** raw text search is only for finding an unknown entry point by
> strings, labels, or comments. The instant you have a symbol name, switch to symbol navigation
> (workspace symbol, find references, incoming calls, hover) and stop tracing that symbol with raw
> text search.

> **Do not over-scope a search.** Behavior for one area is often split across several trees - an
> app-layer event subscriber can change base-application behavior with no call edge into it, so a
> search restricted to the folder you first suspect will silently miss the real cause. If the root
> cause is still unfound, drop the path filter and search the whole repository.

**When the affected area is unknown** (but an error message or object reference exists): symbol
search for the AL objects, procedures, or tables named in the issue; text search for error-message
substrings and comments not tied to a known symbol; file matching for module patterns such as
`**/*Sales*.al`; then read the candidates to confirm relevance.

**When the area is known but the root cause is not**: list the document symbols of the file for a
structural overview; find references on the suspect procedure or field to locate callers and usages;
trace incoming calls into the buggy code and outgoing calls for its dependencies. Look for missing
null checks, incorrect filter logic, off-by-one errors, wrong `Get`/`Find` handling, and unhandled
edge cases. `git log --oneline -10 -- <file-path>` shows what changed there recently.

**When the expected behavior is unclear**: hover for type information and documentation comments,
and read the existing test codeunits that exercise the affected procedure - they encode the intended
contract. Read them only; never edit them (Rule 1).

Issue images, when the task references them, are under `problem/` at the repository root. Read them
if the described symptom is visual.

### Step 2: Write the plan

Hold the plan in memory - do not write it to a file (Rule 4). It must cover:

- **Root cause** - 2-4 sentences naming the file, the procedure, and the line-level logic error.
- **Confidence** - `high` / `medium` / `low`, plus what remains unverified and every assumption you
  made about the unattended run's missing information.
- **Proposed fix** - a numbered list of concrete changes, each naming the file and describing the
  edit ("add a null check before accessing `Rec.Field` in procedure `PostSalesOrder`").
- **Affected files** - each with a one-line reason.
- **Acceptance criteria** - the observable behavior that must change, plus "no regressions in
  related workflows".

**Validate the plan's symbols before implementing.** Confirm every procedure, table, codeunit, page,
and report it names exists in the workspace and that the target procedure or trigger is present in
the file you intend to edit. Correct the name or path before touching code.

---

## Phase 2: Implement and Validate

A self-correcting loop, at most 5 iterations. Complete each iteration to its end before deciding
anything (Rule 14); stop only between iterations.

### a. Implement or adjust the fix

On the first iteration, implement the plan. On later iterations, read the failure from the previous
iteration and adjust: if every iteration fails the same way, the approach is wrong rather than
incomplete, so revisit the root cause instead of patching the symptom.

Make targeted edits to the files named in the plan. Keep the change minimal, respect the existing
style, and add no bug-reference comments (Rule 6).

### b. Compile

Build every project you modified with `al_build`. Inspect failures with `al_getdiagnostics`, correct
them, and rebuild - a compile fix is not a new iteration. On a missing-symbol error apply Rule 11.

### c. Publish (only when you intend to run tests)

Publish the modified app with `al_publish`. Publishing is only worth its cost if step d follows;
skip it otherwise.

> A dependency-chain publish can reinstall the container's **stock** copy of a dependent app over a
> locally built one, silently reverting what you just deployed. Version numbers do not expose this,
> because stock and locally built apps normally share the same app ID and version. So when you run
> tests, publish the app the tests live in **last**, as its own explicit call, using the artifact
> path its build returned.

### d. Run existing tests (optional regression check)

Only if the AL tools are advertised and an existing test codeunit covers the affected behavior. Run
it with `al_run_tests`, passing the integer `codeunitId`. This is a regression check on tests that
already exist - never write a new test to make this step possible (Rule 1), and never run the full
suite, which does not fit the run budget.

A test that fails because it asserts behavior the issue says is wrong is information, not a defect
in your fix: the harness supplies the authoritative test. Weigh it against the plan's acceptance
criteria rather than editing the test.

### e. Decide

- **Green** (clean build, and tests pass where you ran them): stop iterating and go to Phase 3.
- **Red**: analyze the failure, and start the next iteration at step a.
- **Iteration 5 exhausted**: stop. Leave the best version of the fix in the working tree and report
  what still fails and what you tried. Do not revert your work - the change is collected either way.

---

## Phase 3: Report

Summarize in a few sentences:

- The root cause and the fix, naming the files and procedures you changed.
- The validation performed: build result, publish and test results when you ran them, or an explicit
  statement that the AL tools were unavailable and the change was not built.
- Any assumption the plan recorded, and anything left unverified.

Do not commit, push, or open a pull request (Rule 3). The working tree is the deliverable.
