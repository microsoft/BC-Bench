# Agent Setup & Rules (Minimal)

## 1. Startup Checks
Both checks are **required** and must pass. Before processing, verify:
1.  **Codebase**: `grep` for "SalesPost" in `**/*.al` returns results.
2.  **Configs**: Ensure existence of YAML files (team-mapping, templates, and at least some requirements/rules). Do not read or open the files.

**Failure**: Report error and halt. **Success**: Print "✅ Argus initialized".

## 2. Scope & Constraints
-   **Agent Mode**: Read-only code. Append-only comments/labels. NO editing code/PRs.
-   **Output**: GitHub comments/labels + console logs only.

## 3. Processing Criteria
-   **Workflow**:
    -   Process issues **sequentially** (one at a time).
    -   **Independence**: Reset context fully between issues. Failures in one issue do not halt the processing of others.
    -   **Logging**: Log "Now starting processing issue #[ID]" at the start and "Issue #[ID] is processed." upon completion.
    -   Skip ineligible issues silently (log internally).

## 4. Format input data as GH_REQUEST (json object):
{
  "number": int (number from instance_id),
  "title": string,
  "description": string,
  "type": string (default is Task),
  "state": string (default is open),
  "labels": string[],
  "author": string (default is N/A),
  "created_at": timestamp (default is current datime),
  "updated_at": timestamp (default is current datime),
  "comments": Comment[]
}
