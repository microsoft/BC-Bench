# Phase 2 — Eligibility check

Decide whether this request should be processed. Reason over `GH_REQUEST` and
`DISTILLED_REQUEST`. No external tools. This runs offline, so there is no issue state,
type, author identity, or timestamp to consider — judge only the request content.

## Checks (all must pass)
1. **Content appropriateness** — title, body, and any comments contain no inappropriate,
   offensive, or abusive content.
2. **Not withdrawn** — the request text does not withdraw/cancel itself (e.g. "withdraw",
   "cancel", "no longer needed", "closing this", "nevermind"), and does not state that an
   agent-suggested alternative now satisfies the requester such that the original is no
   longer needed (e.g. "this alternative works for me", "I no longer need the original
   approach"). If withdrawn → `FailureLabel: close`.

## Outcomes
| Condition | IsEligible | FailureLabel |
|-----------|-----------|--------------|
| All checks pass | true | `""` |
| Withdrawal detected | false | `close` |
| Check 1 fails (inappropriate content) | false | `agent-not-processable` |

If not eligible, set `FailureReason` and go to **Phase 7** (subject to the Phase 2b
resolution in the orchestrator).

## Output
```json
{ "IsEligible": true, "FailureLabel": "", "FailureReason": "" }
```
