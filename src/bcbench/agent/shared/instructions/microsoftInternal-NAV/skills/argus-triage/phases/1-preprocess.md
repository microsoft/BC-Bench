# Phase 1 — Preprocess the issue thread

Extract the core extensibility request from `GH_REQUEST`. No external tools — reason over
the thread you already loaded.

Read the full thread and extract only what is needed for technical evaluation. If the
author revised their request in comments, use the **latest** version. Include answers the
author gave to agent/reviewer questions — these often carry justification or clarification
absent from the original post. Ignore greetings, bot replies, off-topic discussion, and
repeated content.

## Extract → `DISTILLED_REQUEST`
- `goal` — what extensibility change the author wants (1–2 sentences)
- `latestRequest` — the most up-to-date version of the request
- `proposedCode` — any AL code, procedure names, or object names mentioned (`""` if none)
- `justification` — the business/technical reason given (`""` if none)
- `clarifications` — key points clarified during the thread, one sentence each
  (`Q: … — A: …`), empty array if none

## Output
```json
{
  "goal": "...",
  "latestRequest": "...",
  "proposedCode": "...",
  "justification": "...",
  "clarifications": ["Q: ... — A: ..."]
}
```
