---
bc-version: [all]
domain: upgrade
keywords: [upgrade-tag, event-subscriber, on-get-per-company-upgrade-tags, on-get-per-database-upgrade-tags, registration]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Register every upgrade tag with the platform via an event subscriber

## Description

The `Upgrade Tag` codeunit only recognizes a tag if the tag was published to the platform through one of two events on that codeunit: `OnGetPerCompanyUpgradeTags` for tags set inside `OnUpgradePerCompany`, and `OnGetPerDatabaseUpgradeTags` for tags set inside `OnUpgradePerDatabase`. A tag that is `Set` and `Has`-checked in code but never added to one of these lists is unknown to the platform — its semantics around skip-on-reinstall, telemetry, and operator queries do not apply.

The registration scope must match where the tag is set: a tag used from `OnUpgradePerCompany` registers in `OnGetPerCompanyUpgradeTags`; a tag used from `OnUpgradePerDatabase` registers in `OnGetPerDatabaseUpgradeTags`. Crossing the scopes silently breaks the tag.

## Best Practice

For every new upgrade tag, add one line to the matching subscriber: `PerCompanyUpgradeTags.Add(MyUpgradeTag());` or `PerDatabaseUpgradeTags.Add(MyUpgradeTag());`. Place the subscribers in the same codeunit (or a dedicated "Upgrade Tag Definitions" codeunit) so the tag string and its registration stay together.

See sample: `register-upgrade-tags-with-subscribers.good.al`.

## Anti Pattern

Calling `UpgradeTag.SetUpgradeTag(MyUpgradeTag())` without ever adding `MyUpgradeTag()` to the corresponding `OnGetPerCompany...` / `OnGetPerDatabase...` subscriber.

See sample: `register-upgrade-tags-with-subscribers.bad.al`.
