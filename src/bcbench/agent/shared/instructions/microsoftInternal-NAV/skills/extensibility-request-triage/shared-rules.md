# Shared rules (binding for every phase)

1. **Advisory only.** The result is reviewed by an engineer. Never present a decision as
   final or take an irreversible action beyond applying managed labels / a comment / a
   state change.

2. **One write moment.** Do not post comments or change labels until Phase 7 has produced
   the result contract. Phases 0–6 are read-and-reason only.

3. **Managed labels only.** You may add or remove exactly these, and nothing else:
   - request-type labels: `event-request`, `request-for-external`, `enum-request`,
     `extensibility-enhancement`
   - team labels: `Finance`, `SCM`, `Integration`
   - failure / status labels: `missing-info`, `agent-not-processable`
   Never edit issue title, body, or assignees.

4. **Respect `/not-accurate`.** If any comment starts with `/not-accurate`, the issue was
   flagged by a human — stop and take no action (`do-nothing`).

5. **Stop early on a decisive outcome.** Eligibility failure, multi-type request,
   auto-reject blocker, already-implemented, or a `reject`/`agent-not-processable`
   requirement each short-circuit the remaining phases. Carry the `FailureLabel` and
   `FailureReason` straight to Phase 7.

6. **Don't re-raise addressed points.** If the author already answered a warning or
   suggestion in the thread (gathered in Phase 1), do not flag it again.

7. **Rules are authoritative, not your judgment.** In Phase 5, if a `warnings` or
   `blockers` condition matches the code, honour it — do not override it with your own
   opinion. Conversely, do not invent blockers that are not in the rule files.

8. **Telemetry/logging is non-fatal.** If a logging or telemetry step fails, continue;
   never let it block or change the triage outcome.

9. **Be concise in the thread.** The posted comment uses the wording from
   `knowledge/comment-templates/comment_templates.yaml` plus the disclaimer and feedback
   footer defined verbatim in `phases/7-finalize.md`. Do not add freeform commentary.

10. **Deterministic state.** Keep all working notes in your own context or a temp file.
    Do not write state into the issues repo or the code repo.
