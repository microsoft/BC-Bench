---
name: extensibility-request-triage
description: >-
  Triage a single Business Central extensibility request end to end: distill the
  thread, check eligibility, classify the request type, validate input requirements,
  analyse feasibility against the local AL source + codebase rules, assign a team, and
  emit labels + an advisory comment + an open/closed decision. Runs unattended.
allowed-tools: [read, search, execute, agent]
---

# extensibility-request-triage

## What this does

Given **one** extensibility request, produce a triage result:

- `labels_to_set` — managed labels (team label + request type, or a failure label such as
  `missing-info` / `agent-not-processable`)
- `comment_to_post` — an advisory comment (may be empty)
- `request_state` — `open`, `closed`, or unchanged

The result is **advisory**. A human reviews before any action is taken.

## Offline mode (evaluation)

This skill runs **offline**: there is no live issue and no GitHub write-back.

- The **request** is supplied as rendered text in the prompt (title + body + any follow-up
  comments + current labels). There is no `ISSUE_NUMBER` and no `gh`.
- The **AL source** is checked out at the caller-supplied **`CODE_ROOT`** (the repository
  root passed by the runner) → Phase 5 reads local files (no remote GitHub API, no
  codebase token).
- The skill + knowledge are installed alongside this file → reference them with paths
  **relative to this skill directory** (e.g. `knowledge/...`, `phases/...`).
- The final decision is written as JSON to **`triage_result.json`** under `CODE_ROOT`
  instead of being applied to any issue.

`compatibility.md` maps every logical capability to a concrete tool for this offline mode.

## How it runs

Follow `orchestrator.md` (Phases 0–7). It reuses the triage knowledge under `knowledge/`:

- `knowledge/input-requirements/*.yaml` — required fields per type (Phase 4)
- `knowledge/codebase-rules/*.yaml` — feasibility rules (Phase 5)
- `knowledge/team-configuration/team_namespace_mapping.yaml` — namespace → team (Phase 6)
- `knowledge/comment-templates/comment_templates.yaml` — comment wording (Phase 7)

`compatibility.md` maps every action to a host tool. `shared-rules.md` lists invariants
binding on all phases.

## Inputs

| Name | Value |
|------|-------|
| `REQUEST_TEXT` | the rendered request (title + body + comments + current labels) from the prompt |
| `CODE_ROOT` | the repository root supplied by the runner (local AL source) |
| `BCAPPS_CHECK` | optional; off by default |

## Output

The result contract in `templates/result-contract.md`, written by Phase 7 to
`triage_result.json` under `CODE_ROOT`.
