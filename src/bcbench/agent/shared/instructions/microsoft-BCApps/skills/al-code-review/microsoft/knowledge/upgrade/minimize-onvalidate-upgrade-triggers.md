---
bc-version: [all]
domain: upgrade
keywords: [on-validate-upgrade-per-company, performance-impact, skip-logic, justification, upgrade-tag]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Performance-impacting upgrade triggers need justification and skip logic

## Description

Triggers such as `OnValidateUpgradePerCompany` run on every upgrade pass. When their body performs non-trivial work — full-table scans, cross-table validations — the cost is paid on every upgrade of every tenant, even when there is nothing to validate. That cost is acceptable only when the validation is critical (regulatory compliance, data-integrity guarantees the platform depends on) AND the trigger short-circuits once it has done its work.

## Best Practice

A performance-impacting upgrade trigger carries two things: a written comment that names the reason the work has to happen on every upgrade pass, and an early-exit guard backed by an upgrade tag so the work runs at most once per tenant. The `HasUpgradeTag` check at the top exits when the validation has already been recorded; the `SetUpgradeTag` call at the bottom records completion.

See sample: `minimize-onvalidate-upgrade-triggers.good.al`.

## Anti Pattern

Doing real work in `OnValidateUpgradePerCompany` with no upgrade-tag guard. The same scan runs every upgrade, multiplying upgrade time by the number of releases the customer takes.

See sample: `minimize-onvalidate-upgrade-triggers.bad.al`.
