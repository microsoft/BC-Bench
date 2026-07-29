---
name: argus-triage
description: >-
  Triage a single Business Central extensibility-request issue end to end: distill the
  thread, check eligibility, classify the request type, validate input requirements,
  analyse feasibility against the local AL source + codebase rules, assign a team, and
  emit labels + an advisory comment + an open/closed decision. Runs unattended.
allowed-tools: [read, search, execute, agent]
---

# argus-triage

## What this does

Given **one** extensibility-request issue in this repo (an open `Task` with no labels or
only `missing-info`), produce a triage result:

- `labels_to_set` — managed labels (team label + request type, or a failure label such as
  `missing-info` / `agent-not-processable`)
- `comment_to_post` — an advisory comment (may be empty)
- `issue_state` — `open`, `closed`, or unchanged

The result is **advisory**. A human reviews before any action is taken.

## Single-repo mode (this repo)

Everything is local in **`microsoft/BCAppsTest`**:

- The **issue** is in this repo → operated on with `gh`.
- The **AL source** is checked out at **`CODE_ROOT = ./src`** → Phase 5 reads local files
  (no remote GitHub API, no codebase token).
- The skill + knowledge are in `internal/Argus_2/`.

## When it triggers

The workflow (`.github/workflows/argus2-extensibility-triage.yml`) runs on a schedule
(discovers eligible issues) and on `workflow_dispatch` (a single issue number for
testing). Eligibility is re-checked in Phase 2.

## How it runs

Follow `orchestrator.md` (Phases 0–7). It reuses the existing triage knowledge under
`knowledge/`:

- `knowledge/input-requirements/*.yaml` — required fields per type (Phase 4)
- `knowledge/codebase-rules/*.yaml` — feasibility rules (Phase 5)
- `knowledge/team-configuration/team_namespace_mapping.yaml` — namespace → team (Phase 6)
- `knowledge/comment-templates/comment_templates.yaml` — comment wording (Phase 7)

`compatibility.md` maps every action to a host tool. `shared-rules.md` lists invariants
binding on all phases.

## Inputs

| Name | Value in this repo |
|------|--------------------|
| `ISSUE_NUMBER` | from dispatch / discovery |
| `REPO` (`owner/repo`) | `microsoft/BCAppsTest` |
| `CODE_ROOT` | `./src` (local AL source) |
| `BCAPPS_CHECK` | optional; off by default (no separate BCApps repo in this test) |

## Output

The result contract in `templates/result-contract.md`, which Phase 7 applies to the issue.
