# Result contract

Phase 7 must emit exactly this object, then write it to `triage_result.json` via
`compatibility.md`.

```json
{
  "Final_Output": {
    "labels_to_set": ["Finance", "event-request"],
    "comment_to_post": "Hi, ...",
    "request_state": "open",
    "failureStep": "",
    "failureReason": ""
  }
}
```

## Field rules

- **`labels_to_set`** — the complete set of *managed* labels the request should end with.
  May be empty (`[]`) for a rejected request.
- **`comment_to_post`** — the advisory comment body, already filled from the chosen
  template in `knowledge/comment-templates/comment_templates.yaml`, with the disclaimer
  and `/not-accurate` feedback footer from `phases/7-finalize.md` appended verbatim.
  Empty string = no comment.
- **`request_state`** — `"open"`, `"closed"`, or `""` (no recommendation, used for
  `do-nothing`).
- **`failureStep`** / **`failureReason`** — diagnostics for logging only; not part of the
  advisory comment.

## Writing it (Phase 7, via compatibility.md)

Write the `Final_Output` object to `triage_result.json` at the caller-supplied output
location. This is the single artifact the eval reads back — there is no live issue to
update, no labels to reconcile on a server, and no comment to post.
