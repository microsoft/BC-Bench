# Orchestrator — extensibility-request-triage

The end-to-end triage procedure. Follow the phases in order. `shared-rules.md` is binding
throughout. Resolve every tool through `compatibility.md`. Each phase below names the
phase file with the detailed instructions and the **state** it contributes.

**Offline mode:** there is no live issue — the request is read from the prompt text
(`REQUEST_TEXT`) and the AL source is local under the caller-supplied `CODE_ROOT`. Phase 5
reads local files — there is no remote code repo.

You accumulate a single `WorkflowState` object as you go. Phases 0–6 only read and reason;
the single decision is emitted once, in Phase 7, to `triage_result.json`.

## State carried between phases

```
GH_REQUEST            # request text parsed into metadata + comments (Phase 0)
DISTILLED_REQUEST     # goal, latestRequest, proposedCode, justification, clarifications (Phase 1)
TYPE, SUBTYPE         # request classification (Phase 3)
OBJECT_LIST           # target AL objects with namespace + path (Phase 5)
SUGGESTED_IMPLEMENTATION  # AL snippet (Phase 5)
TEAM_LABEL            # responsible team (Phase 6)
FailureLabel          # "" or one of: missing-info | agent-not-processable | close | bcapps | do-nothing | already-implemented
FailureReason         # human-readable reason carried to Phase 7
```

Whenever a phase sets a non-empty `FailureLabel`, **skip to Phase 7** (short-circuit) —
except where a phase explicitly says to continue.

---

## Phase 0 — Startup  →  `phases/0-startup.md`

Confirm the local AL source exists at `CODE_ROOT` and the knowledge files are present.
Parse the request text into `GH_REQUEST` (title, body, comments, current labels). If a
comment starts with `/not-accurate`, set `FailureLabel: do-nothing` and go to Phase 7.

## Phase 1 — Preprocess  →  `phases/1-preprocess.md`

Distill the thread into `DISTILLED_REQUEST`. *(Light; inline.)*

## Phase 2 — Eligibility  →  `phases/2-eligibility.md`

Apply the six eligibility checks. Set `FailureLabel` per the outcome table. If not
eligible, go to Phase 7. *(Inline.)*

## Phase 2b — BCApps check  →  `phases/2b-bcapps-check.md`  *(optional)*

**Off by default in this repo** — there is no separate BCApps repo in the test setup.
Run only if `BCAPPS_CHECK` is enabled and a BCApps remote is configured; otherwise treat
as `FoundInBCApps: false` and continue to Phase 3.

## Phase 3 — Classify  →  `phases/3-classify.md`

Determine `TYPE` and `SUBTYPE`. Multiple distinct types → `missing-info`. Pure bug →
`agent-not-processable`. Failures → Phase 7. *(Inline.)*

## Phase 4 — Requirements  →  `phases/4-requirements.md`

Read `knowledge/input-requirements/*.yaml` for `general` + `TYPE` (+ `SUBTYPE`) and check
the request has every required field. Matched `reject` → `close`; matched
`agent-not-processable` → that label; missing fields → `missing-info`. Failures → Phase 7.

## Phase 5 — Codebase analysis  →  `phases/5-codebase-analysis.md`  **(dispatched)**

The heavy phase. **Pre-load the rules first**, then dispatch a sub-agent (ladder in
`compatibility.md`) so the local search/read work runs in its own context.

1. Determine the rule file set for `TYPE`/`SUBTYPE` the same way the original `ruleLoader`
   does — for each category (`blockers`, `alternative_suggestions`, `warnings`,
   `implementation`), collect in order, skipping any that don't exist:
   - `knowledge/codebase-rules/general_<category>.yaml`
   - `knowledge/codebase-rules/<typePrefix>_<category>.yaml`
   - `knowledge/codebase-rules/<typePrefix><subtypeSuffix>_<category>.yaml`

   `typePrefix`: `event-request→event_request`, `request-for-external→request_for_external`,
   `enum-request→enum_request`, `extensibility-enhancement→extensibility_enhancement`.
   `subtypeSuffix`: `ishandled→_ishandled`, `new_enum→_new_enum`,
   `extend_existing_enum→_extend_existing_enum`, `regular→` (none). Read those YAML files
   and assemble the `RULES` batches.

2. Dispatch Phase 5:
   - prompt: »
       Read `phases/5-codebase-analysis.md` (relative to this skill directory) and follow
       it with:
       DISTILLED_REQUEST: <json>
       TYPE: <type>   SUBTYPE: <subtype>
       CODE_ROOT: <the caller-supplied repository root>
       RULES: <assembled blockers/alternativeSuggestions/warnings/implementation>
       Return only the Phase 5 JSON contract.
     «

3. From the returned JSON set `OBJECT_LIST`, `SUGGESTED_IMPLEMENTATION`, and any
   `FailureLabel` (`auto-reject`, `already-implemented`, `missing-info`,
   `agent-not-processable`). If blocked/rejected → Phase 7.

## Phase 6 — Team assignment  →  `phases/6-team-assignment.md`

Map `OBJECT_LIST` namespaces to a `TEAM_LABEL` via
`knowledge/team-configuration/team_namespace_mapping.yaml`. No match →
`agent-not-processable` → Phase 7. *(Inline.)*

## Phase 7 — Finalize  →  `phases/7-finalize.md`

Work **only** from `WorkflowState`. Use the decision table to choose `labels_to_set`, the
comment template, and `request_state`. Emit the result contract
(`templates/result-contract.md`) and **write it to `triage_result.json`** via
`compatibility.md`. The only phase that writes.

---

## Note: shared knowledge

The `knowledge/` folder here is self-contained: it carries its own requirements and
codebase-rules so the skill needs no external package. Keep requirements and rules in this
folder in sync when they change.
