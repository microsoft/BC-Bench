# Requirements Check (Minimal)

**Purpose:** Validate issue against all requirement layers (General + Type + Sub-Type).

## Core Logic
1.  **Load Configs:** Load `general_requirements.yaml` and type-specific YAMLs (e.g., `event_request_requirements.yaml`).
2.  **Execute Checks:** Run checks sequentially (General -> Type -> Sub-Type).
    *   **Fail Fast:** If any check triggers `agent-not-processable`, stop immediately and return failure.
    *   **Collect Failures:** For other failures (e.g., missing info), continue running all checks to report all missing items at once.
3.  **Mandatory Logging:**
    *   Format: `{PASS|FAIL} | {requirement_name} - {one sentence summary}`
4.  **Output:**
    Return a JSON object:
    *   `Success`: (boolean) True if request met all requirements.
    *   `FailureLabel`: (string) `missing-info` or `agent-not-processable` (only if `Success` is `false`).
    *   `FailureReason`: (string) Consolidated explanation of all failures.

## Configuration Sources
*   `input-requirements/general_requirements.yaml`
*   `input-requirements/{type}_requirements.yaml` (event_request, request_for_external, enum, etc.)

**Note:** All validation rules, criteria, and max iterations are defined in these YAML files.
