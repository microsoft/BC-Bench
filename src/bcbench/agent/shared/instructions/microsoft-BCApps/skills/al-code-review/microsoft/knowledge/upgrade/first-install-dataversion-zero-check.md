---
bc-version: [all]
domain: upgrade
keywords: [dataversion, first-install, on-install-app-per-company, moduleinfo, zero-version]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Detect first install with `DataVersion() = Version.Create('0.0.0.0')`

## Description

On the first install of an extension on a tenant the platform records a zero data version: `AppInfo.DataVersion()` returns `Version.Create('0.0.0.0')`. Subsequent upgrades record the actual previous version. The `OnInstallAppPerCompany` trigger uses this distinction to detect a brand-new install — for example, to seed default rows that should not be re-inserted on a normal upgrade. This is the one place where reading `DataVersion()` is the right tool; for everything else, use an upgrade tag.

## Best Practice

In `OnInstallAppPerCompany`, fetch the current `ModuleInfo` via `NavApp.GetCurrentModuleInfo`, compare `AppInfo.DataVersion()` to `Version.Create('0.0.0.0')`, and run install-only seed logic only when they match. On any non-zero data version, exit immediately — that path is an upgrade, not an install.

See sample: `first-install-dataversion-zero-check.good.al`.

## Anti Pattern

Treating `OnInstallAppPerCompany` as if it always implies "fresh tenant". The trigger also fires when reinstalling over an existing data set; without the `0.0.0.0` guard, install-only seed code re-runs on every upgrade and duplicates rows.

See sample: `first-install-dataversion-zero-check.bad.al`.

## See also

- `use-upgrade-tags-not-version-checks.md` — for upgrade steps after first install, use upgrade tags rather than `DataVersion`.
