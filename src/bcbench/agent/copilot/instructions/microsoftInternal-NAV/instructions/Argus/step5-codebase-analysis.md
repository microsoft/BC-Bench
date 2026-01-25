# Codebase Analysis

**Purpose:** Verify feasibility, check rules, and generate implementation guidance.

## Core Logic
1.  **Identify Targets:** Determine which objects should be updated based on the request.
    - **Action:** Generate `ObjectList` (only objects where changes are required).
2.  **Load Configurations:** Load `general_implementation_rules.yaml` and type-specific YAMLs (e.g., `event_request_implementation_rules.yaml`).
3.  **Process Objects:** For each object in `ObjectList`:
    - **Locate Code:** Find the object in the codebase (only search in `.al` files) (use **Tools:** `semantic_search`, `grep_search`, `file_search`).
        - **Priority:** Search in the W1 layer first (even if another layer is mentioned in the request); if not found, search in other locations.
        - **Failure Condition:** If not found, return `agent-not-processable`.
    - **Apply Rules per Inquiry:** For every individual inquiry (e.g., multiple event requests for the same object):
        - **Verify Target:** Confirm procedure/trigger logic.
            - **Trigger missing?** Create new (Allowed).
            - **Procedure missing?** Return `missing-info`.
        - **Check Existence:** Is the request already implemented?
            - **Exact Match:** Mark as `ALREADY_IMPLEMENTED`.
        - **Validate Rules:** Apply **ALL** rules from configuration files to determine the best solution.
            - **Track Progress:** Count total rules vs. rules successfully checked for the log.
            - **Blocker?** Auto-reject/Stop. Return `FailureLabel: "auto-reject"` and `FailureReason` from the rule.
            - **Warning?** Note in guidance.
            - **Action:** Generate `SuggestedImplementation` based on the request analyzed with implementation rules.
4.  **Multi-Change:** Apply all-or-nothing logic for mixed statuses.
5.  **Mandatory Logging:**
    *   Format: `{PASS|FAIL} | {requirement_name} - {one sentence summary}`
6.  **Output:**
    Return a JSON object:
    *   `Success`: (boolean) True if request met all requirements.
    *   `OBJECT_LIST`: (Array) List of objects involved. Each item includes:
        *   `Type`: (string) e.g., Codeunit, Table.
        *   `Id`: (integer) Object ID.
        *   `Name`: (string) Object name.
        *   `Namespace`: (string).
    *   `SUGGESTED_IMPLEMENTATION`: (string) Explanation with code snippets of what is suggested to implement (only if `Success` is `true`).
    *   `FailureLabel`: (string) `missing-info`, `agent-not-processable`, or `auto-reject` (only if `Success` is `false`).
    *   `FailureReason`: (string) Consolidated explanation of all failures.

## Configuration Sources
*   `implementation-rules/general_implementation_rules.yaml`
*   `implementation-rules/{type}_implementation_rules.yaml` (e.g., `event_request`, `request_for_external`, `enum`)
