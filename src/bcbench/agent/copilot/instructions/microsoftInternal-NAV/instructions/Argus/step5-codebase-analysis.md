# Codebase Analysis

**Purpose:** Verify feasibility through progressive rule evaluation and generate implementation guidance.

## Core Logic

1.  **Understand Intent:** Determine what the author wants to accomplish based on the request, including analysis of all existing comments.

2.  **Identify Targets:** Determine which objects should be updated based on the request.
    - **Action:** Generate `ObjectList` (only objects where changes are required).

3.  **Locate Code:** For each object in `ObjectList`:
    - Find the object in the codebase using `grep` to search `.al` files by object name or ID. Use targeted patterns such as the object name or numeric ID — **do NOT use broad glob patterns like `**/*.al`**.
        - Example: `grep("codeunit 5880", "**/*.al")` or `grep("Phys. Invt. Order-Finish", "**/*.al")`
        - **Priority:** Search in the W1 layer first (even if another layer is mentioned in the request); if not found, search in other locations.
        - **Failure Condition:** If not found, return `agent-not-processable`.
    - **Verify Target:** Confirm procedure/trigger logic.
        - **Trigger missing?** Create new (Allowed).
        - **Procedure missing?** Return `missing-info`.

4.  **Progressive Rule Evaluation:** For each inquiry, apply rules in the following order:

    ### a) **BLOCKER RULES** (Stop on First Match)
    - Load: `codebase-rules/{type}_blockers.yaml` + `codebase-rules/{type}_{subtype}_blockers.yaml` (if subtype specified) + `general_blockers.yaml`
    - **Purpose:** Identify requests that cannot be processed (auto-reject scenarios).
    - **Behavior:** If ANY blocker rule matches, STOP immediately and return failure.
    - **Action:** Return `FailureLabel: "auto-reject"` with `FailureReason` from the rule.
    - **Track Progress:** Count total blocker rules vs. rules checked.

    ### b) **ALTERNATIVE SUGGESTION RULES** (Evaluate All)
    - Load: `codebase-rules/{type}_alternative_suggestions.yaml` + `codebase-rules/{type}_{subtype}_alternative_suggestions.yaml` (if subtype specified) + `general_alternative_suggestions.yaml`
    - **Purpose:** Check if existing functionality can satisfy the request (with or without small modifications).
    - **Behavior:** Evaluate ALL suggestion rules before proceeding.
    - **Action:** If ANY suggestion applies, STOP further execution. Return `FailureLabel: "missing-info"` with all suggestions listed in `FailureReason`. Author must confirm if suggestion is acceptable or if new implementation is still needed.
    - **Track Progress:** Count total suggestion rules vs. rules checked.

    ### c) **WARNING RULES** (Evaluate All)
    - Load: `codebase-rules/{type}_warnings.yaml` + `codebase-rules/{type}_{subtype}_warnings.yaml` (if subtype specified) + `general_warnings.yaml`
    - **Purpose:** Identify requests that require justification, clarification, or author confirmation.
    - **Behavior:** Check ALL warning rules before returning. Accumulate all warnings.
    - **Action:** If ANY warnings apply, STOP further execution. Return `FailureLabel: "missing-info"` with all warnings listed in `FailureReason`. Author must provide clarification/justification.
    - **Track Progress:** Count total warning rules vs. rules checked.

    ### d) **IMPLEMENTATION RULES** (Apply All)
    - Load: `codebase-rules/{type}_implementation.yaml` + `codebase-rules/{type}_{subtype}_implementation.yaml` (if subtype specified) + `general_implementation.yaml`
    - **Purpose:** Ensure suggested solution aligns with coding standards and best practices.
    - **Prerequisite:** Only execute if NO suggestions and NO warnings were triggered in previous steps.
    - **Behavior:** Apply ALL implementation rules to the proposed solution.
    - **Action:** Generate `SuggestedImplementation` following all applicable rules.
    - **Track Progress:** Count total implementation rules vs. rules checked.

5.  **Graceful Rule Handling:**
    - If a rule file doesn't exist, log it and continue with available rules.
    - Always apply general rules (if available) even when type-specific rules are missing.
    - **CRITICAL:** Agent MUST include ALL available rules from loaded files in the analysis.

6.  **Check Existing Implementation:**
    - **Exact Match:** Mark as `ALREADY_IMPLEMENTED` (check before applying rules).

7.  **Multi-Change Logic:** Apply all-or-nothing logic for mixed statuses.

8.  **Mandatory Logging:**
    - Format: `{PASS|FAIL|SKIP} | {category}/{rule_id} - {one sentence summary}`
    - Example: `PASS | blocker/obsolete_code - Target code is not obsolete`
    - Example: `FAIL | warning/recordref_parameter - RecordRef parameter requires justification`
    - Example: `SKIP | implementation/event_naming - Rule file not found`

9.  **Output:**
    Return a JSON object:
    - `Success`: (boolean) True if request met all requirements (no blockers, no alternative suggestions, no warnings).
    - `OBJECT_LIST`: (Array) List of objects involved. Each item includes:
        - `Type`: (string) e.g., Codeunit, Table.
        - `Id`: (integer) Object ID.
        - `Name`: (string) Object name.
        - `Namespace`: (string).
    - `SUGGESTED_IMPLEMENTATION`: (string) Explanation with code snippets of what is suggested to implement (only if `Success` is `true`).
    - `FailureLabel`: (string) `missing-info`, `agent-not-processable`, or `auto-reject` (only if `Success` is `false`).
    - `FailureReason`: (string) Consolidated explanation of all failures, suggestions, or warnings requiring author response.

## Configuration Sources

### Rule File Structure
Rules are organized by category, type, and subtype:

**General Rules (apply to all types):**
- `codebase-rules/general_blockers.yaml`
- `codebase-rules/general_alternative_suggestions.yaml`
- `codebase-rules/general_warnings.yaml`
- `codebase-rules/general_implementation.yaml`

**Type-Specific Rules:**
- `codebase-rules/{type}_blockers.yaml` (e.g., `event_request_blockers.yaml`)
- `codebase-rules/{type}_alternative_suggestions.yaml`
- `codebase-rules/{type}_warnings.yaml`
- `codebase-rules/{type}_implementation.yaml`

**Subtype-Specific Rules (if applicable):**
- `codebase-rules/{type}_{subtype}_blockers.yaml` (e.g., `event_request_ishandled_blockers.yaml`)
- `codebase-rules/{type}_{subtype}_alternative_suggestions.yaml`
- `codebase-rules/{type}_{subtype}_warnings.yaml`
- `codebase-rules/{type}_{subtype}_implementation.yaml`

**Loading Strategy:**
- General rules are always loaded
- Type-specific rules are loaded based on the request type
- Subtype-specific rules are loaded only when a subtype is specified in the request
- Agent loads rules ad hoc per category (not all at once)

**Note:** Not all category files may exist initially. Agent must handle missing files gracefully and log them.
