---
bc-version: [all]
domain: upgrade
keywords: [upgrade-codeunit, subtype, on-upgrade-per-company, on-upgrade-per-database, trigger]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Upgrade logic must live in a codeunit with `Subtype = Upgrade`

## Description

A codeunit only participates in the upgrade pipeline when it sets `Subtype = Upgrade`. The platform then dispatches the `OnUpgradePerCompany` and `OnUpgradePerDatabase` triggers on that codeunit during upgrade. A codeunit without `Subtype = Upgrade` — even one that declares an `OnUpgradePerCompany` trigger — is not an upgrade codeunit, and reviewers ignore it for upgrade concerns. Conversely, any procedure invoked transitively from an `OnUpgrade...` trigger of an upgrade codeunit IS upgrade code regardless of where it lives, and the upgrade rules apply to it.

## Best Practice

Place every piece of upgrade logic in a codeunit declared with `Subtype = Upgrade;` and expose entry points via the two triggers `OnUpgradePerCompany` and `OnUpgradePerDatabase`. Helper procedures may live in normal codeunits, but they inherit the upgrade-context rules (guarded reads, no external calls, upgrade tags, etc.) when called from an upgrade trigger.

See sample: `upgrade-codeunit-subtype.good.al`.

## Anti Pattern

Putting upgrade-style logic in a regular codeunit that the platform never invokes during upgrade — for example a normal codeunit with a manually invented "RunUpgrade" procedure that nothing wires to the upgrade pipeline. The migration code will simply not run.

See sample: `upgrade-codeunit-subtype.bad.al`.
