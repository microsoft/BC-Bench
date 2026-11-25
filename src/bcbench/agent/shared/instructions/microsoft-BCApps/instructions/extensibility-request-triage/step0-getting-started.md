# Step 0: Startup Checks

Verify the environment before processing begins.

**Offline mode:** there is no live issue and no `gh`. The request is supplied as rendered
text in the prompt (`REQUEST_TEXT`), and the AL source is checked out locally at the
caller-supplied repository root (`CODE_ROOT`). The knowledge files are installed next to
these step files under `TRIAGE_ROOT = .github/instructions/extensibility-request-triage`.

**Checks (both required, must pass):**
1. **Codebase**: `glob` for `<CODE_ROOT>/**/*.al` (or `**/SalesPost.Codeunit.al`) returns
   at least one result — confirms the local AL source is present.
2. **Configs**: confirm the knowledge YAML files exist under `TRIAGE_ROOT`
   (`team-configuration`, `comment-templates`, and at least some `input-requirements` /
   `codebase-rules`). Do not open or read them yet.

If either check fails, return `Success: false` with the reason and stop.

## Format the input as `GH_REQUEST`

Parse `REQUEST_TEXT` (title + body + any follow-up comments + current labels) into a
`GH_REQUEST` object. There is no live issue to fetch — everything comes from the prompt.

```json
{
  "title": string,
  "description": string,
  "type": "Task",
  "state": "open",
  "labels": string[],
  "comments": [ { "body": string } ]
}
```

Fields not present in `REQUEST_TEXT` take these defaults: `type = "Task"`,
`state = "open"`, `labels = []` (unless current labels are supplied), `comments = []`.

**Return JSON:**
```json
{
  "Success": true,
  "FailureReason": ""
}
```
