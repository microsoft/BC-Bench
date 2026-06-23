---
bc-version: [all]
domain: privacy
keywords: [tobeclassified, data-classification, release, appsource, development]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Resolve every `ToBeClassified` before release

## Description

`DataClassification = ToBeClassified` is the sentinel value the AL compiler accepts while a developer has not yet decided what a new field actually stores. It exists for the development phase only and must be resolved to a real classification (`CustomerContent`, `EndUserIdentifiableInformation`, `EndUserPseudonymousIdentifiers`, `AccountData`, `OrganizationIdentifiableInformation` or `SystemMetadata`) before the code ships. A released field left at `ToBeClassified` tells the platform "we have not classified this data" — which means GDPR data-subject requests, telemetry and audit reports cannot reason about it.

## Best Practice

Treat `ToBeClassified` as a TODO marker that fails release readiness. Sweep new table objects and table extensions for it before submitting a build for publication. If the right classification is genuinely unclear, decide between `CustomerContent` and `EndUserIdentifiableInformation` from the data's content, not from convenience.

## Anti Pattern

Leaving `ToBeClassified` in a shipped extension. Reviewers who treat the value as "I'll figure it out later" ship a field whose privacy posture is undefined for every customer that installs the app.
