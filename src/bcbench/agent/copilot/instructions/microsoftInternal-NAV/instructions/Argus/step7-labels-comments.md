# Labels & Comments

**Purpose:** Finalize issue by applying labels, posting comments, and closing if needed.

**Rule:** All comments must be generated using templates from `comment-templates/comment_templates.yaml` corresponding to the situation.

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

## 3. Execution Order
1. **Generate JSON Output:** Produce a JSON object with the following structure:
   ```json
   {
     "label": [], // Labels to add
     "comment": "", // The comment content
     "status": "" // "open" or "closed"
   }
   ```
