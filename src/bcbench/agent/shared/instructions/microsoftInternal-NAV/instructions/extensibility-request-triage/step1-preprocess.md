# Step 1: Preprocess Request Thread

Extract the core extensibility request from the request thread.

**Input:** `GH_REQUEST` — title, description, and all comments (from `REQUEST_TEXT`).

Read the full thread and extract only what is needed for technical evaluation. If the author revised their request in comments, use the latest version. Also include answers the author gave in response to agent or reviewer questions — these often contain justification or clarification not present in the original post. Ignore greetings, bot replies, off-topic discussion, and repeated content.

**Extract:**
- `goal` — what extensibility change the author wants (1–2 sentences)
- `latestRequest` — the most up-to-date version of the request
- `proposedCode` — any AL code, procedure names, or object names mentioned (empty string if none)
- `justification` — the business or technical reason given (empty string if none)
- `clarifications` — list of key points clarified during the thread; for each, briefly summarize what was asked and what the author explained (1 sentence each, empty array if none)

**Return JSON:**
```json
{
  "goal": "...",
  "latestRequest": "...",
  "proposedCode": "...",
  "justification": "...",
  "clarifications": ["Q: ... — A: ...", "Q: ... — A: ..."]
}
```
