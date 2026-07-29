# Compatibility — capabilities → host tools

Argus-triage describes actions as **logical capabilities**. Resolve each to a concrete
tool on the current host. This repo runs the skill via the **Copilot CLI**
(`--allow-all-tools --allow-all-paths`), in a checkout of **this same repo**, so:

- The **issue** lives in this repo → use `gh` against the current repo.
- The **AL source** is local at `CODE_ROOT` (`./src`) → use local file tools, **not** the
  remote GitHub API.

Detect what is available once at the start and use the first working option per capability.

## Issue capabilities (this repo)

| Capability | Tool |
|---|---|
| Read issue metadata | `gh issue view <N> --json number,title,body,state,labels,author,createdAt,updatedAt` |
| Read issue type | `gh api repos/{owner}/{repo}/issues/<N> --jq '.type.name'` |
| List all comments | `gh api --paginate repos/{owner}/{repo}/issues/<N>/comments --jq '.[] \| {user:.user.login, body, createdAt:.created_at}'` |
| Post a comment | `gh issue comment <N> --body-file <file>` |
| Add labels | `gh issue edit <N> --add-label "<a>,<b>"` |
| Remove a label | `gh issue edit <N> --remove-label "<x>"` |
| Close the issue | `gh issue close <N>` |

`{owner}/{repo}` come from the run context (`REPO`). `gh` authenticates from `GH_TOKEN`.

> Only ever **add/remove the managed labels** listed in `shared-rules.md`. Never touch
> labels you do not manage, and never edit issue title, body, or assignees.

## Code capabilities (LOCAL source under `CODE_ROOT` = `./src`)

| Capability | Tool |
|---|---|
| Search by filename | `find ./src -type f -iname '<File>.al'` (or the `glob` tool: `src/**/<File>.al`) |
| Search by content | `grep -rn --include='*.al' '<pattern>' ./src` (or the `grep` tool) |
| Find file in tree | same as "search by filename" — the whole tree is local |
| Read a file | `read` / `cat` on the matched `./src/...al` path (read the whole file) |
| Grep within a file | `grep -n -C3 '<pattern>' <path>` |

There is no remote code repo and no codebase token in this mode — the source is checked
out alongside the skill. AL filename derivation is unchanged (CamelCase + `.Type.al`).

## Knowledge capabilities (local files under this skill)

| Capability | Tool |
|---|---|
| Read a knowledge YAML | `read` / `cat` on `internal/Argus_2/skills/argus-triage/knowledge/<...>.yaml` |
| Read a phase / template | `read` / `cat` on `internal/Argus_2/skills/argus-triage/<...>.md` |

## Sub-agent dispatch ladder (Phase 5)

Dispatch to the first available rung and announce which one you used:

1. **Named custom agent** — only if this host registers `argus-codebase-analysis`
   (cloud-agent hosting). Not available under the plain Copilot CLI.
2. **Generic sub-agent** — the CLI `task` tool with a `general-purpose` agent, passing the
   Phase 5 file path and inputs. *(Preferred under Copilot CLI.)*
3. **Inline** — if no sub-agent tool is available, run Phase 5 yourself in the current
   context.

Emit: `Dispatch: Phase 5 via rung <n> (<tool>) because rungs above are <reason>.`
