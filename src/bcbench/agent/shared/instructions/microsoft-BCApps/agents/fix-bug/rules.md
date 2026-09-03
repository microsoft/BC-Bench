# Rules for the fix-bug Workflow

These rules apply to every step of `workflow.md`.

## Hard constraints

1. **Product code only.** Do not create or edit test codeunits, test projects, or any other testing
   logic. The reproducing test is supplied by the harness after the run, and edits to test projects
   are reverted before the change is evaluated, so time spent there is wasted.

2. **W1 only.** Fix the W1 layer. Do not propagate the change to country layers (DK, NL, DE, APAC,
   …) and do not edit files outside W1 to make a localization consistent.

3. **No git writes.** Never commit, stage, branch, reset, stash, or push, and never use `gh`. The
   working tree *is* the deliverable: the harness collects the diff after the run. Leave any
   pre-existing uncommitted changes alone.

4. **Nothing scratch inside the repository.** Plans, notes, logs, and state files go to `$env:TEMP`,
   never into the repository. Any extra `.al` file under the repo root lands in the collected diff
   and counts against the change.

5. **Do not touch the environment.** The repository, the BC container, and the AL tools are
   provisioned by the harness. Never provision, restart, or reconfigure a container, never install
   packages, and never edit `app.json` version numbers, `launch.json`, or CI configuration to make
   something build.

6. **Keep the change minimal and idiomatic.** Fix the root cause, not the symptom; respect the
   surrounding code style, naming, and error handling. Do not reformat untouched code, and do not
   add comments that reference a bug number, issue ID, or this workflow.

7. **One pass, no waiting.** The run is unattended: there is no approval gate and no user to ask.
   Where information is missing, record the assumption in your plan and continue.

## Using the AL tools

8. **The AL tools are the only sanctioned way to build, publish, and test.** Never invoke `alc.exe`,
   `msbuild`, `Publish-NAVApp`, `Import-NAVApp`, `docker`, or BcContainerHelper, and never try to
   reach the BC service directly. If the AL tools are not advertised in this session, the task is
   code-change-only: implement the fix by reading and reasoning about the code, and say in your
   report that it was not built.

   Core tool names: `al_build`, `al_getdiagnostics`, `al_downloadsymbols`, `al_publish`,
   `al_run_tests`, `al_symbolsearch`.

9. **Detect the tool prefix once.** The AL tools are namespaced by the MCP server registration, so
   the callable name depends on the harness (`altool-al_build`, `mcp__altool__al_build`, or bare
   `al_build`). At the start of the run, find the advertised tool whose name ends in `al_build`,
   take the text before `al_build` as the prefix, and apply that prefix to every AL tool call
   afterwards.

10. **Connection details are already configured.** The AL tool server is started by the harness with
    the container's server URL, instance, and credentials, so call the tools without hunting for
    connection values. This category may also expose `BC_*` variables in your own environment; they
    are not yours to use - reaching the container with them instead of through the AL tools breaks
    Rule 8.

11. **Missing symbols**: on `AL0185`, `AL1022`, or a similar missing-symbol error, call
    `al_downloadsymbols` **once**, then rebuild. If the type belongs to a namespace the file has not
    imported, add the `using <Namespace>;` instead - that is a code error, not a symbol error.

12. **Never search the filesystem for `.app` files.** Take the artifact path from the build result.

13. **Build cost is real.** A BaseApp build can take tens of minutes against a per-run budget that
    also has to cover investigation and implementation. Build the projects you changed, batch your
    edits before building, and do not rebuild to confirm a build you have already seen succeed.

## Failure handling

14. **Compile errors and failing tests are feedback, not failures.** Inspect them with
    `al_getdiagnostics`, correct the code, and continue the loop.

15. **Infrastructure failures are terminal.** A hung or timed-out AL tool, a tool that is not
    advertised, a publish that fails or times out, or a developer endpoint that stops answering is
    not something to work around. Do not retry more than the one retry `troubleshooting.md` allows,
    do not permute the call's parameters, and do not look for a way around the tool. Stop, leave the
    fix in the working tree, and report what failed - the change is still collected, so a preserved
    working tree is worth far more than a session spent fighting the container.

## Output guidelines

Report progress as short natural-language summaries: what you found, what you changed, and how it
validated. Parse tool output silently; do not paste raw compiler, publish, or test output unless it
is the error you are explaining. Never print credentials.
