# Labels & Comments

**Purpose:** Finalize issue by applying labels, posting comments, and closing if needed.

**Rule:** All comments must be generated using templates from `comment-templates/comment_templates.yaml` corresponding to the situation.

**Output Format:** Return a JSON object with the following structure:
```json
{
  "labels_to_apply": ["label1", "label2"],
  "comment_to_post": "Generated comment text using template",
  "state_of_issue": "open" or "closed"
}
```

## 1. Prerequisites (Mandatory)
- Verify **ALL** previous steps completed if outcome is `FEASIBLE`.
- If outcome is `MISSING_INFO` or `AGENT_NOT_PROCESSABLE`, partial completion is valid.

## 2. Decision Logic

### A. Success (Feasible)
- **Labels:** Team (e.g., "Finance") + Type (e.g., "event-request"). Added as a pair.
- **Comment:** "✅ Analysis complete - approved for implementation". Include existing/pending code.
- **Status:** Open.

### B. Missing Info
- **Labels:** `missing-info` **ONLY**. (No Type/Team labels).
- **Comment:** Explain what is missing/needed.
- **Status:** Open.

### C. Agent Not Processable
- **Labels:** `agent-not-processable` **ONLY**.
- **Comment:** None.
- **Status:** Open.

### D. Auto Reject
- **Labels:** None.
- **Comment:** "This request cannot be implemented." + Reason.
- **Status:** **Close** (Reason: not planned).

### E. Already Implemented
- **Labels:** None.
- **Comment:** "✅ Already implemented." Show code snippets.
- **Status:** **Close** (Reason: completed).

### F. Stale Issue (30+ days inactive)
- **Labels:** Maintain `missing-info`.
- **Comment:** "Closing due to inactivity."
- **Status:** **Close** (Reason: not planned).

## 3. Output Requirements
1. **Labels Array:** List only the labels to be added/set. If transitioning from one state to another (e.g., from `missing-info` to feasible), include only the final labels (stale labels will be removed automatically).
2. **Comment Text:** Generate using templates from `comment-templates/comment_templates.yaml`. Select the template matching the request type and outcome (e.g., `approved_event_request` for feasible requests).
3. **State:** Set to `"open"` or `"closed"` based on the decision logic above (closed for outcomes D, E, F).
