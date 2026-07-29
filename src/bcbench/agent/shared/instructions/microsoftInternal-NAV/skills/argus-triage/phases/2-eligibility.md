# Phase 2 — Eligibility check

Decide whether this issue should be processed. Reason over `GH_REQUEST` and
`DISTILLED_REQUEST`. No external tools.

## All six checks must pass
1. Issue `state` is `open`.
2. Issue `type` is `Task`.
3. Labels are empty **or** only `missing-info` is set.
4. If `missing-info` is present: the **bot is not** the last commenter **and** last
   activity (`updatedAt`) was within **30 days**.
5. **Content appropriateness** — body and comments contain no inappropriate, offensive,
   or abusive content.
6. **Author withdrawal** — the author's most recent comment does not withdraw/cancel the
   request (e.g. "withdraw", "cancel", "no longer needed", "closing this", "nevermind"),
   and does not confirm that an agent-suggested alternative now satisfies them such that
   they no longer need the original (e.g. "this alternative works for me", "I no longer
   need the original approach"). If withdrawn → `FailureLabel: close`.

## Outcomes
| Condition | IsEligible | FailureLabel |
|-----------|-----------|--------------|
| All checks pass | true | `""` |
| `missing-info` + no activity 30+ days | false | `close` |
| Author withdrawal detected | false | `close` |
| Check 5 fails (inappropriate content) | false | `agent-not-processable` |
| `missing-info` + bot **is** last commenter | false | `do-nothing` |
| Any other failure | false | `do-nothing` |

If not eligible, set `FailureReason` and go to **Phase 7** (subject to the Phase 2b
resolution in the orchestrator).

## Output
```json
{ "IsEligible": true, "FailureLabel": "", "FailureReason": "" }
```
