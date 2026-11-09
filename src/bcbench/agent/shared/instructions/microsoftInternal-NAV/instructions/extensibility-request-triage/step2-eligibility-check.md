# Step 2: Eligibility Check

Decide whether this request should be processed.

**Input:** `GH_REQUEST` (metadata: state, labels, type, comments) and `DISTILLED_REQUEST`.

**Offline note:** there is no live issue, author identity, or activity history — timestamp-
and commenter-based checks do not apply. Evaluate eligibility from the request metadata and
the thread content only.

**All checks below must pass:**
1. Request state is `open`.
2. Request type is `Task`.
3. Labels are empty OR only `missing-info` is set.
4. **Content Appropriateness**: body and comments must not contain inappropriate, offensive, or abusive content.
5. **Requester-Confirmed Closure**: the most recent comment must not indicate that no new change is needed because the requester withdrew or cancelled the request (e.g., "withdraw", "cancel", "no longer needed", "closing this", "nevermind") or accepted an existing solution or alternative suggested by the agent (e.g., "this alternative works for me", "I can use this event", "thank you for the change"). Set `FailureLabel: "close"` and preserve the actual reason in `FailureReason`. When an existing solution was accepted, include its name and any signature or file details already present in the thread. Do not describe requester-confirmed closure as stale or inactive.

**Outcomes:**

| Condition | IsEligible | FailureLabel |
|-----------|-----------|--------------|
| All checks pass | true | `""` |
| Requester-confirmed closure detected | false | `"close"` |
| Check 4 fails (inappropriate content) | false | `"agent-not-processable"` |
| Any other failure | false | `"do-nothing"` |

**Return JSON:**
```json
{
  "IsEligible": true,
  "FailureLabel": "",
  "FailureReason": ""
}
```
