# Issue Eligibility Check

**Purpose:** Validate issue meets criteria for automated processing.

## Core Logic
An issue is **ELIGIBLE** if it passes **ALL** checks:
1.  **Issue State**: Must be `open`.
2.  **Issue Type**: Must be `Task`.
3.  **Recency**: If `missing-info` label is present, last activity must be < 30 days ago (failure marks as `IsStale`).
4.  **Labels**:
    *   **No Labels**: No Microsoft team member (excluding bot) involved.
    *   **"missing-info" Label Only**: Author must be the last commenter.
    *   **Other Labels**: Not eligible.

## Output Format
Return a JSON object:
   *   `IsEligible`: (boolean) True if **ALL** checks pass
   *   `IsStale`: (boolean) True if "missing-info" label exists AND no activity > 30 days
   *   `FailureReason`: (string) Reason for ineligibility (only if NOT Eligible)


## Decision Matrix

| Condition | IsEligible | IsStale | FailureReason |
| :--- | :--- | :--- | :--- |
| **All Checks Pass** | `true` | `false` | `` |
| **Issue Closed** | `false` | `false` | "Issue is closed" |
| **"missing-info" > 30 days** | `false` | `true` | "No activity for 30+ days" |
| **Wrong Type** | `false` | `false` | "Type is not Task" |
| **Team Involved** | `false` | `false` | "Microsoft team member involved" |
| **Agent Last Comment** | `false` | `false` | "Waiting for author response" |
| **Other Labels** | `false` | `false` | "Already processed" |
