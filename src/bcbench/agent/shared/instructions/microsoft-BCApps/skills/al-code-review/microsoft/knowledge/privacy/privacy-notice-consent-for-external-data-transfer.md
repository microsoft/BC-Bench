---
bc-version: [all]
domain: privacy
keywords: [privacy-notice, consent, http-client, outgoing-request, external-service, getprivacynoticeapprovalstate]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Outgoing requests to external services require a Privacy Notice consent check

## Description

Business Central ships a built-in Privacy Notice framework that the admin uses to grant or withhold per-integration consent for sending data to external services. The relevant API surface is `Codeunit "Privacy Notice"` (consent checks via `GetPrivacyNoticeApprovalState()`), `Codeunit "Privacy Notice Registrations"` (well-known notice IDs for integrations such as Exchange, OneDrive, Teams), and the `Enum "Privacy Notice Approval State"` with values `Agreed`, `Disagreed`, and `Not Set`. The admin UI is the **Privacy Notices Status** page. The compliance concern in code review is therefore not that personal data is included in an outgoing HTTP body — that is normal business functionality — but that the code path issuing the request contains no `PrivacyNotice.GetPrivacyNoticeApprovalState(...)` check.

## Best Practice

Before issuing an outgoing HTTP request to an external service, verify `PrivacyNotice.GetPrivacyNoticeApprovalState(<integration id>) = "Privacy Notice Approval State"::Agreed`. The check does not have to live next to the `HttpClient.Post` call — it can sit anywhere upstream in the same code path (for example in the page's `OnOpenPage`, in a wizard step, or in a setup action) as long as no execution path reaches the request without passing through it.

See sample: `privacy-notice-consent-for-external-data-transfer.good.al`.

## Anti Pattern

A `procedure SendDataToExternalService(...)` that posts customer data to an external endpoint with no `PrivacyNotice.GetPrivacyNoticeApprovalState` anywhere upstream. The same anti-pattern applies in reverse: removing an existing privacy-notice check from code that still issues the external call.

See sample: `privacy-notice-consent-for-external-data-transfer.bad.al`.
