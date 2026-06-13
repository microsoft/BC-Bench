---
bc-version: [all]
domain: upgrade
keywords: [hybrid-migration, hybrid-bc14, hybrid-sl, hybrid-gp, hybrid-base-deployment, one-time-migration]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Hybrid migration codeunits are not standard upgrade codeunits

## Description

Codeunits like `HybridBC14`, `HybridSL`, `HybridGP`, and `HybridBaseDeployment` implement one-time migration paths from a specific source system into Business Central. They run in a different pipeline from the standard per-company / per-database upgrade triggers and follow patterns shaped by that source — staging tables, schema-mapped imports, and per-source post-processing. The rules that apply to standard upgrade codeunits — guarded reads, no external calls, `DataTransfer` for bulk init, `Subtype = Upgrade`, upgrade tags — are not the right yardstick for these migration codeunits.

## Best Practice

Treat a hybrid migration codeunit as a domain of its own. If you need to add or modify migration logic, follow the conventions of the surrounding hybrid migration codebase (which has its own dispatcher, its own way of recording progress, and its own error handling) rather than imposing standard upgrade conventions on it. Conversely, do not borrow hybrid-migration patterns into standard upgrade codeunits — the platform contract is different.

When reviewing changes inside a hybrid migration codeunit, do not flag missing upgrade tags, missing `Subtype = Upgrade`, or missing `OnUpgradePerCompany` wiring. None of those apply.

## Anti Pattern

Reviewing a change inside `HybridBC14` / `HybridSL` / `HybridGP` / `HybridBaseDeployment` against standard upgrade rules and flagging the absence of `Subtype = Upgrade` or upgrade-tag plumbing.
