# Team Assignment

**Purpose:** Assign ownership based on object namespaces.

## Core Logic
1.  **Extract Namespaces:** Get namespaces from all target objects.
    - **Failure Condition:** If none found, return `agent-not-processable` and stop.
2.  **Match Teams:** Compare extracted namespaces against configuration settings.
    - **Preprocessing:** Remove "Microsoft" prefix if present (e.g., `Microsoft.Sales.History` -> `Sales.History`).
    - **Strategy:** Iterative fallback matching:
        1.  Try full remaining namespace.
        2.  If no match, remove last segment and retry (e.g., `Sales.History` -> `Sales`).
        3.  Repeat until match found or only root segment remains.
3.  **Determine Winner:**
    - Count matches per team.
    - **Tie-Breaker:** If counts are equal, select the alphabetically first team.
    - **Failure Condition:** If no matches, return `agent-not-processable` and stop.
4.  **Output:**
    Return a JSON object:
    *   `Success`: (boolean) True if owning team found.
    *   `TEAM_LABEL`: (string) Found team name `Finance` or `Integration` or `SCM` (only if `Success` is `true`).
    *   `FailureLabel`: (string) `agent-not-processable` (only if `Success` is `false`).
    *   `FailureReason`: (string) Explanation of failure.

## Configuration Sources
*   `team-configuration/team_namespace_mapping.yaml`
