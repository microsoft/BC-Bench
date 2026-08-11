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
5. **Author Withdrawal**: the most recent comment must not indicate the request is being withdrawn or cancelled (e.g., phrases like "withdraw", "cancel", "no longer needed", "closing this", "nevermind"). Also treat as withdrawal when the author confirms that an alternative approach suggested by the agent satisfies their need and they explicitly state they no longer need the original request (e.g., "this alternative works for me", "I no longer need the original approach", "thank you for the change"). If withdrawn, set `FailureLabel: "close"` — no further processing needed.

**Outcomes:**

| Condition | IsEligible | FailureLabel |
|-----------|-----------|--------------|
| All checks pass | true | `""` |
| Author withdrawal detected | false | `"close"` |
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
