---
bc-version: [all]
domain: performance
keywords: [singleton, setup-table, sales-receivables-setup, general-ledger-setup, setloadfields, bounded]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Singleton setup tables hold one row; access-pattern optimization is wasted

## Description

Business Central setup tables — `Sales & Receivables Setup`, `General Ledger Setup`, `FA Setup`, `Purchases & Payables Setup`, and the broader pattern of any `*Setup` table — hold at most one record per company. Per the upstream guidance, "any access pattern is fine, no `SetLoadFields` needed" on these tables. The same applies to other small bounded tables (enum mappings, permission objects, Role IDs) and system metadata tables (`TableMetadata`, `Field`, `AllObjWithCaption`) where iteration is safe.

## Best Practice

Skip access-pattern optimization on singleton-setup-style tables. `SalesReceivablesSetup.Get()` does not need `SetLoadFields` (see `use-setloadfields-for-partial-records.md`); a `repeat ... until` over a permission-object table does not need bulk operations. Spend the review attention on the production-scale tables instead (see `production-scale-tables-warrant-extra-analysis.md`).

## Anti Pattern

Mechanically applying the rules in this domain to every `Record` variable in the codebase. Flagging "missing `SetLoadFields`" on `GeneralLedgerSetup` or "use `IsEmpty` instead of `FindSet`" on a setup table adds noise without payoff — the optimization saves nothing measurable on a one-row table — and trains readers to ignore the review channel.
