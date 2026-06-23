---
bc-version: [all]
domain: performance
keywords: [admin-page, migration, wizard, hybrid, permissions, lower-severity]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Admin and migration pages tolerate lower performance discipline

## Description

Some pages run rarely and against small datasets, and the upstream guidance explicitly calls for treating them as lower severity. Per the review checklist, "Admin/migration pages (`Admin`, `Setup`, `Wizard`, `Migration`, `HybridBC14`, `HybridSL`, `HybridGP` namespaces, `Permissions`/`PermissionSet` pages) are infrequently used with small datasets — apply lower severity." The same logic covers one-time wizards and tenant-bootstrap routines: the code path runs a handful of times in the lifetime of a tenant, against a bounded dataset, by an administrator.

## Best Practice

When triaging a finding on an admin, migration, or wizard page, downgrade severity relative to the same finding on a hot business path. A `FindSet` loop without `SetLoadFields` on a migration page that processes setup records once per tenant is a different finding than the same loop on a posting routine that runs thousands of times a day. Note this context explicitly in the review so the call site is not "fixed" twice with diminishing returns.

## Anti Pattern

Treating a migration wizard's per-row loop with the same urgency as the same loop in `Sales-Post`. The fix cost is the same; the production benefit is not. Bulk-rewriting an admin page to use `ModifyAll` and partial records buys nothing the user will perceive.
