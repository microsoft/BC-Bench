# Allow retrieving Outlook emails unsanitized via bypass flag

## What & why

Lets first-party callers retrieve Outlook emails **without** body sanitization. `Email - Outlook API Helper` now passes `not Filters.GetBypassBodySanitization()` to `EmailMessage.Create` instead of a hard-coded `true`. Sanitization stays on by default; only callers that explicitly call `SetBypassBodySanitization(true)` keep the raw body. That API is `[Scope('OnPrem')]` on the *Email Retrieval Filters* table, so 3rd-party AppSource extensions cannot opt out — only on-prem, first-party (Microsoft) code can.

This is the GitHub counterpart of an internal Azure DevOps PR (NAV repo #250087); porting it here since the app is migrating to microsoft/BCApps.

## Linked work

Related ADO work item: [AB#640361](https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_workitems/edit/640361) — *Expense Agent: provide full (unsanitized) email content to handle complex HTML receipts*.

## How I validated this

- [ ] I read the full diff and it contains only changes I intended.
- [ ] I built the affected app(s) locally with no new analyzer warnings.
- [ ] I ran the change in Business Central and confirmed it behaves as expected.
- [x] I added or updated tests for the new behavior, or explained below why none are needed.

**What I tested and the outcome**

- Added two tests in `OutlookAPIHelperTests.Codeunit.al`: `TestRetrieveEmailSanitizesBodyByDefault` (unsafe `<script>`/`onerror` stripped by default) and `TestRetrieveEmailBypassSanitizationKeepsRawBody` (raw body preserved when bypass is set), backed by a new `RetrieveEmailWithUnsafeBody.txt` response fixture.
- The `Email - Outlook REST API` app compiles against current `main` (the `GetBypassBodySanitization`/`SetBypassBodySanitization` API is already present in the System Application). Full in-product test run still pending on a complete BC environment.

## Risk & compatibility

Low. Default behavior is unchanged (bodies remain sanitized). The opt-out is gated to on-prem first-party callers via `[Scope('OnPrem')]`. No schema, upgrade, or permission changes.


