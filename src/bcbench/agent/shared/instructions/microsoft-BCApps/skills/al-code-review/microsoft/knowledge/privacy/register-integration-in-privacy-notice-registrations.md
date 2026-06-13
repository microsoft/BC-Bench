---
bc-version: [all]
domain: privacy
keywords: [privacy-notice-registrations, integration, register, exchange, onedrive, teams, notice-id]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Register every new external integration with `Privacy Notice Registrations`

## Description

`Codeunit "Privacy Notice Registrations"` is the registry of integrations whose consent state the platform tracks. Built-in integrations such as Exchange, OneDrive and Teams already have notice IDs exposed via accessor methods on this codeunit (`GetExchangePrivacyNoticeId`, etc.); a new integration introduced by an extension must add itself to the registry so that the admin can grant or withhold consent on the **Privacy Notices Status** page. Without registration, there is nothing for `Codeunit "Privacy Notice"` to return an approval state for — the call cannot meaningfully gate the outbound request.

## Best Practice

When introducing a new outbound integration: pick a stable notice ID, register it via `Privacy Notice Registrations`, and then gate every outbound call with `PrivacyNotice.GetPrivacyNoticeApprovalState(<that id>)` as described in `privacy-notice-consent-for-external-data-transfer.md`.

See sample: `register-integration-in-privacy-notice-registrations.good.al`.

## Anti Pattern

Shipping a new outbound integration without registering it. Even if the code calls `GetPrivacyNoticeApprovalState`, the admin has no surface to express consent — the integration is effectively unmanaged from a privacy-notice standpoint.
