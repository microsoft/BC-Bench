# Result contract

Phase 7 must emit exactly this object, then apply it to the issue via `compatibility.md`.

```json
{
  "Final_Output": {
    "labels_to_set": ["Finance", "event-request"],
    "comment_to_post": "Hi @author, ...",
    "issue_state": "open",
    "failureStep": "",
    "failureReason": ""
  }
}
```

## Field rules

- **`labels_to_set`** — the complete set of *managed* labels the issue should end with.
  The applier removes managed labels that are not in this list and adds those that are.
  Unmanaged labels are left untouched. May be empty (`[]`) for a closed/rejected issue.
- **`comment_to_post`** — the advisory comment body, already filled from the chosen
  template in `knowledge/comment-templates/comment_templates.yaml`, with the disclaimer
  and `/not-accurate` feedback footer from `phases/7-finalize.md` appended verbatim.
  Empty string = post nothing.
- **`issue_state`** — `"open"`, `"closed"`, or `""` (leave unchanged, used for
  `do-nothing`).
- **`failureStep`** / **`failureReason`** — diagnostics for logging only; never shown to
  the author.

## Applying it (Phase 7, via compatibility.md)

1. If `issue_state` is `""` and there is nothing to post → take no action (`do-nothing`).
2. Reconcile labels: remove managed labels not in `labels_to_set`; add the rest.
3. If `comment_to_post` is non-empty → post it (write to a file and use `--body-file`).
4. If `issue_state` is `"closed"` → close the issue.

This mirrors what `process-issue.sh` does in the original Argus, but performed by the
agent through host tools instead of a shell wrapper.
