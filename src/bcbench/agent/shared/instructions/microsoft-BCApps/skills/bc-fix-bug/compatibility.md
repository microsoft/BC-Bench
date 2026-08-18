<!-- Vendored from microsoft/BCAppsBugFix@74425ca226bea2dc1736e0e527f5c2d9578b1379, trimmed for BC-Bench (TDD core only). -->

# Host Compatibility Map

This skill runs, unattended, in two hosts that expose different tools:

- The GitHub Copilot CLI.
- Claude Code.

Never hard-code a single host's tool name in a phase. Instead, resolve the capability you
need from the table below and use the first listed tool that your host actually exposes. The
`git` and PowerShell commands are available in both hosts via the shell and may be used directly.
There is no network access to any issue tracker or source control host; never call `gh` or `az`.

## Capability resolution (first available wins)

| Capability | Use this, else fall back |
|---|---|
| Read a file | `view`, else `read_file` |
| Create a file | `create`, else `create_file` |
| Edit a file | `edit`, else `replace_string_in_file` or `multi_replace_string_in_file` |
| Search code | `grep` and `glob`, else `grep_search` and `file_search` |
| Run a shell command | `powershell`, else `run_in_terminal` |
| Dispatch a phase sub-agent | Follow the ladder in "Phase sub-agent dispatch" below; emit the `Dispatch:` line |
| Build an AL project | the AL build tool `al_build` (see prefix rule) |
| Publish an AL app | the AL publish tool `al_publish` (see prefix rule) |
| Read build diagnostics | the AL diagnostics tool `al_getdiagnostics`, else parse the build output |
| Download or search symbols | `al_downloadsymbols` or `al_symbolsearch`, else skip |
| Run AL tests | the AL test tool `al_run_tests` (see prefix rule), else the PowerShell fallback below |
| Investigate code structure | `lsp` when `.github/lsp.json` exists, else `grep`, `glob`, and `view` |

## AL tool prefix rule

The AL MCP tools may be namespaced by the host's MCP server registration, so the same tool can
have a different full name per host (for example `altool-al_build` or bare `al_build`). The core
names are identical: `al_build`, `al_publish`, `al_getdiagnostics`, `al_downloadsymbols`,
`al_compile`, `al_symbolsearch`, `al_run_tests`. At the start of a run, detect the prefix once:
inspect the advertised tool whose name ends in `al_build`, take the text before `al_build` as the
prefix, and apply that prefix to every AL tool call for the rest of the run.

## Run AL tests

Call the AL test tool (`<prefix>al_run_tests`) with `codeunitId` set to the integer test codeunit
ID. This works in both hosts.

There is no fallback. The `Run-TestsInBcContainer` fallback that used to live here is blocked by
the `preToolUse` hook along with the rest of BcContainerHelper (see `shared-rules.md` Rule 2). If
no AL test tool is advertised, the environment is broken - stop and report the failure instead of
driving the container yourself.

Parse the output to decide next steps.

## Phase sub-agent dispatch

Phases 2 (baseline) and 3 (implement) run in a sub-agent, not inline - the separate context window
is the point of the phase design. Resolve the tool by walking this ladder top to bottom and
stopping at the first rung whose tool exists:

1. **Named custom agent** - the phase's agent (`bc-fix-baseline` / `bc-fix-implement`).
   - `task` tool with `agent_type` set to that name, only if that name appears in the `task`
     tool's `agent_type` enum.
2. **Generic sub-agent** - `task` tool with `agent_type: "general-purpose"`. This is always advertised
   in the Copilot CLI, so the ladder stops here at the latest in the CLI. Pass the phase's prompt to it.
3. `runSubagent`, if advertised.
4. **Inline** - only when none of rungs 1-3 are advertised. Because rung 2 is always present in the
   Copilot CLI, inline is not reached there.

Immediately before starting Phase 2 and Phase 3, output one line in this form and then act on it:
`Dispatch: Phase <2|3> via rung <1|2|3|4> (<tool name>) because rungs above it are <unavailable reason>.`
Choose rung 4 only when that line names a concrete, verified reason each of rungs 1-3 is unavailable;
"simpler to do inline", "I can finish in a few calls", or "to keep context" are not valid reasons.

**Dispatch must be synchronous (blocking) - never background/async.** When the dispatch tool exposes
a run mode (e.g. the `task` tool's `mode`), you MUST set it to `sync` and MUST NOT set it to
`background` (or any async/detached equivalent). The orchestrator must keep the current turn active
until the sub-agent finishes and its result has been read; it must not end its turn, yield, or "wait
for a completion notification" while a phase sub-agent is still running. Rationale: under the Copilot
CLI in non-interactive `-p` mode, the process exits as soon as the top-level assistant response ends.
A backgrounded sub-agent is then killed mid-work, yet the run prints a clean end-of-session summary
and exits 0 - a false success that silently abandons the bug fix. Background dispatch only stays alive
in an interactive session, which this skill must never depend on.
