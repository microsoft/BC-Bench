# Implementation Rules - Action Reference

When defining a new rule, you **must** specify an `action` that determines what the agent does when the rule is triggered.

---

## Available Actions

### `auto_reject`

**Purpose:** Immediate, strict rejection - the issue is closed without further processing.

**Agent Behavior:**
- Post rejection comment explaining the reason (uses `rejection_reason` field)
- Close the issue with `state_reason = "not_planned"`
- Do **NOT** apply any labels
- **STOP** all processing - no further steps

**When to Use:**
- Absolute blockers that cannot be resolved (obsolete code, protected code, merge conflicts)
- Requests that violate fundamental rules (e.g., IsHandled in OnDelete trigger)
- Security violations (sensitive data exposure)

**Example Rules:** `obsolete_code`, `protected_code`, `merge_conflicts`, `sensitive_data_exposure`, `ishandled_in_ondelete_trigger`

---

### `request_clarification`

**Purpose:** Request more information from the author before proceeding.

**Agent Behavior:**
- Post clarification comment asking for specific information
- Apply `missing-info` label **ONLY** (no type labels)
- **STOP** processing - wait for author response
- Resume processing after author provides clarification

**When to Use:**
- Target procedure/trigger not found in expected location
- Request is ambiguous or incomplete
- Need confirmation about specific technical details

**Example Rules:** `procedure_not_found`, `existing_event_may_satisfy_request`

---

### `request_justification`

**Purpose:** Request detailed justification from the author for a specific design choice.

**Agent Behavior:**
- Post comment explaining why justification is needed
- Apply `missing-info` label **ONLY** (no type labels)
- **STOP** processing - wait for author response
- Evaluate justification when provided and decide to approve or reject

**When to Use:**
- Author requests something that carries risk (e.g., xRec parameter)
- Author requests something that may have unintended consequences
- Need to understand the business reason behind a technical choice

**Example Rules:** `xrec_parameter_in_event`, `internal_procedure_exposure`, `events_in_loops`

---

### `suggest_alternative`

**Purpose:** Propose a better alternative approach to the author.

**Agent Behavior:**
- Post comment explaining the alternative and why it's better
- Apply `missing-info` label **ONLY** (no type labels)
- **STOP** processing - wait for author confirmation
- If author accepts alternative, implement it; if author insists on original, evaluate further

**When to Use:**
- There's a better way to achieve the author's goal
- The requested approach has performance or design issues
- An existing event could satisfy the request

**Example Rules:** `similar_events_exist`, `ishandled_in_loops`, `integration_event_include_sender_true`, `ishandled_large_code_block_extraction`

---

### `include_human`

**Purpose:** Escalate to human review - the agent cannot make this decision alone.

**Agent Behavior:**
- Do **NOT** post any comment explaining why human review is needed
- Apply `agent-not-processable` label
- **STOP** processing - wait for human decision
- Do **NOT** make any implementation decisions

**When to Use:**
- Complex scenarios that require human judgment
- Edge cases not covered by existing rules
- Situations with significant business impact
- When agent confidence is low

**Example Scenarios:** Conflicting requirements, unclear ownership, architectural decisions

---

### `internal_warning`

**Purpose:** Non-blocking warning - note the issue but continue processing.

**Agent Behavior:**
- Do **NOT** post any comment explaining the warning in the final approval/analysis comment
- Log [WARNING] comment
- **CONTINUE** to next step - does not block processing

**When to Use:**
- Minor concerns that don't block implementation
- Performance considerations the team should be aware of
- Best practice suggestions that aren't mandatory
- Information the implementing team should know

**Example Rules:** `manual_binding_for_heavily_used_procedures`

---

## Action Selection Guidelines

| Scenario | Recommended Action |
|----------|-------------------|
| Violates fundamental rule, cannot proceed | `auto_reject` |
| Missing required information | `request_clarification` |
| Risky choice, need to understand why | `request_justification` |
| Better alternative exists | `suggest_alternative` |
| Agent cannot decide, needs human | `include_human` |
| Minor concern, can proceed | `internal_warning` |

---

## Action Properties

Each action may use different properties from the rule definition:

| Action | Common Properties Used |
|--------|----------------------|
| `auto_reject` | `rejection_reason`, `documentation_link` |
| `request_clarification` | `clarification_template`, `suggestion` |
| `request_justification` | `warning_message`, `confirmation_required_message` |
| `suggest_alternative` | `suggestion_template`, `warning_message` |
| `include_human` | `escalation_reason` |
| `internal_warning` | `warning_message`, `guidance` |


## Severity Levels

When defining a rule, you **must** specify a `severity` that indicates how critical the rule violation is.

### `warning`

**Purpose:** Less critical issue - can be resolved with clarification or minor adjustments.

**Behavior:**
- The issue is flagged but may be resolvable with additional information
- Can be paired with any action depending on the situation
- Does not necessarily mean the request is fundamentally wrong

**When to Use:**
- Situations that need clarification but aren't fundamentally problematic
- Performance considerations the team should be aware of
- Best practice suggestions that may have valid exceptions
- Minor concerns that could be addressed with justification

**Example:** A rule that requests clarification about a specific parameter choice - the request isn't wrong, just needs more context.

---

### `blocking`

**Purpose:** Critical issue - the request cannot be implemented as-is.

**Behavior:**
- The request as submitted **cannot proceed** in its current form
- Requires finding an alternative solution, strong justification, or rejection
- The author's original approach has a fundamental problem

**When to Use:**
- The requested implementation violates design principles or security rules
- There is a better alternative that should be used instead
- The request requires significant rework or a different approach
- Auto-rejection scenarios (obsolete code, protected code, etc.)

**Example:** A rule that rejects adding an event to obsolete code, or suggests an alternative approach because the original request has design issues.

---

### `notice`

**Purpose:** Informational - the rule explicitly allows something or provides guidance.

**Behavior:**
- The rule documents that a specific pattern or change is **allowed**
- No action required from the author - processing continues
- Serves as documentation for the agent on what IS permitted

**When to Use:**
- Rules that explicitly permit certain changes (e.g., adding `var` modifier is allowed)
- Patterns that might seem risky but are actually safe
- Documenting exceptions to other rules
- Guidance rules that don't require any action

**Example:** A rule that states adding `var` to an existing event parameter is a non-breaking change and is allowed.

---
