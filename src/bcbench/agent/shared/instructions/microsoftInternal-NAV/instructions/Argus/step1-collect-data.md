# Issue Data Collection

**Purpose:** Collecting data for the issue from repository `microsoft/ALAppExtensions`.

## Core Logic
1. **Fetch data** Use GitHub MCP server to fetch issue data, comments, and labels.
    *   **Fetch Details**: Use `github_issue_read` with `method: "get"`.
    *   **Fetch Comments**: Use `github_issue_read` with `method: "get_comments"`. Sort chronologically by `created_at`.
    *   **Fetch Labels**: Use `github_issue_read` with `method: "get_labels"`.
2. **Store collected data** as `GH_REQUEST` (json object):
```json
{
  "number": int,
  "title": string,
  "description": string,
  "type": string,
  "state": string,
  "labels": string[],
  "author": string,
  "created_at": timestamp,
  "updated_at": timestamp,
  "comments": Comment[]
}
```
3. **Output:**
    Return a JSON object:
    *   `Success`: (boolean) True if retrieval successful
    *   `GH_REQUEST`: (object) Populated data object with GitHub issue data
    *   `FailureReason`: (string)  Error message ("Failed to retrieve issue #N") if failed to retrieve issue details
