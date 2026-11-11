# General Blockers

Applies to **all** request types. Evaluate these before any type-specific rule; a match here overrides drafting.

## Action vocabulary
Used across every rule file:
- **Auto-reject** — the request cannot be filed as described; explain why and stop.
- **Block; suggest alternative** — do not draft as asked; offer the specified alternative.
- **Request justification** — proceed only if the required reasoning is supplied.
- **Request clarification** — ask a specific question before drafting.
- **Apply directly** — an implementation rule the advisor enforces without asking.

## Blockers
### Obsolete code
**Trigger:** the target is marked `[Obsolete]` or sits inside a `#if not CLEAN` region (indicators: `[Obsolete`, `ObsoleteState`, `ObsoleteReason`, `NOT CLEAN`).
**Action:** Auto-reject — deprecated code must not be modified.

### Breaking public signature change
**Trigger:** the change alters a public procedure signature — adding, removing, reordering, or retyping parameters; changing the return type; or adding/removing a `var` modifier.
**Action:** Auto-reject. *Exception:* naming a previously unnamed return value is non-breaking and allowed.

### Sensitive-data exposure
**Trigger:** the change would expose sensitive data — DotNet interop, `SecretText`, PII, financial credentials or tokens, password hashes, internal system configuration, or protected audit data.
**Action:** Auto-reject. Standard business data (names, addresses, VAT numbers, emails) is not sensitive and does not trigger this rule.

### Security-sensitive surface
**Trigger:** the target touches security keywords — password, secret, token, key, permission, user, login, auth, credential, encryption.
**Action:** Request clarification and flag for manual review. Confirm no secret is exposed and no security check is bypassed before proceeding.

### Multi-change request with a blocked element
**Trigger:** a request bundles several changes and at least one is independently blocked.
**Action:** Auto-reject the entire request. Do not file the feasible parts while dropping the blocked one.

### Target not found
**Trigger:** the named procedure, trigger, or member does not exist at the stated location.
**Action:** Request clarification — confirm the object type/ID and member name. *Exception:* when the request is to add an event inside a trigger that does not yet exist, treat creating that trigger as part of the change.
