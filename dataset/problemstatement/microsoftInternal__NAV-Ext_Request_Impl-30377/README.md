# Extensibility request: extension point in report 10135 "Item Sales Statistics" before the "print only if sales" skip

## Why this change is needed

Report 10135 "Item Sales Statistics" (an NA local report) computes an item's `Sales (Qty.)`
FlowField in the `Item` data item's `OnAfterGetRecord` trigger, and, in the same statement block,
immediately decides whether to skip the record based on the report's `PrintOnlyIfSales` option:

```al
CalcFields("Sales (Qty.)", "Sales (LCY)", "COGS (LCY)");
if ("Sales (Qty.)" = 0) and PrintOnlyIfSales then
    CurrReport.Skip();
```

`PrintOnlyIfSales` is a private global with no accessible getter, and the skip decision is made
before any extension trigger runs. An extension that computes its own sales figure (for example an
alternate unit-of-measure total from its own ledger sums) therefore cannot influence whether a record
is printed: an item the extension considers to have real sales can be silently skipped, and an item
the extension considers zero-sales can still print.

We need an extension point that exposes the already-computed skip decision so a subscriber can
override it in either direction.

## Requested change

Add a new integration event to report 10135 "Item Sales Statistics", raised in the `Item` data
item's `OnAfterGetRecord` trigger **immediately after** the existing `CalcFields` call and
**before** the `PrintOnlyIfSales` skip check.

- Introduce a local `SkipRecord: Boolean` variable in the trigger.
- Assign it the existing skip condition (`("Sales (Qty.)" = 0) and PrintOnlyIfSales`).
- Raise the new event passing the `Item` record and `PrintOnlyIfSales`, and the `SkipRecord` flag by
  reference so a subscriber can override it.
- Replace the original condition with `if SkipRecord then CurrReport.Skip();`.

Illustrative shape (final event name and signature must follow BC event conventions):

```al
SetRange("Variant Filter");
CalcFields("Sales (Qty.)", "Sales (LCY)", "COGS (LCY)");
SkipRecord := ("Sales (Qty.)" = 0) and PrintOnlyIfSales;
// new integration event raised here, passing Item, PrintOnlyIfSales, and SkipRecord (var)
if SkipRecord then
    CurrReport.Skip();
```

## Scope

- File: `App/Layers/NA/BaseApp/Local/Inventory/Reports/ItemSalesStatistics.Report.al`
- This is an NA local report that exists only in the NA layer, so the change lives in the NA layer
  alone (no other country/region layer counterparts to propagate to).
