# Extensibility request: extension point in table 5409 "Prod. Order Routing Line" before ModifyCapNeedEntries

## Why this change is needed

In table 5409 "Prod. Order Routing Line", the `"No."` field `OnValidate` trigger transfers work
center or machine center fields (via `WorkCenterTransferFields` / `MachineCtrTransferFields`) and then
immediately updates capacity need entries by calling `ModifyCapNeedEntries`.

An extension that needs to run custom logic **after** all the standard transfer logic has completed
but **before** capacity need entries are recalculated has no way to hook in: there is no event raised
at this exact point in the execution flow. In particular, a subscriber that needs to evaluate both the
current and previous values of the routing line (`Rec` and `xRec`) after the transfer, but before
`ModifyCapNeedEntries`, cannot do so today.

## Requested change

Add a new integration event to table 5409 "Prod. Order Routing Line", raised in the `"No."` field
`OnValidate` trigger **immediately after** the `case Type of` block (that performs the work/machine
center field transfer) and **immediately before** the `ModifyCapNeedEntries` call. The event should
pass the current record and the previous record (`xRec`) so subscribers can compare them.

Illustrative shape (final event name and signature must follow BC event conventions):

```al
case Type of
    Type::"Work Center":
        begin
            WorkCenter.Get("No.");
            WorkCenter.TestField(Blocked, false);
            WorkCenterTransferFields();
        end;
    Type::"Machine Center":
        begin
            MachineCenter.Get("No.");
            MachineCenter.TestField(Blocked, false);
            MachineCtrTransferFields();
        end;
end;
// new integration event raised here, passing Rec and xRec
ModifyCapNeedEntries();
```

## Scope

- Table 5409 "Prod. Order Routing Line" is kept as a separate copy in the W1 base layer and in the IT
  layer. The change must be applied consistently to both copies:
  - `App/Layers/W1/BaseApp/Manufacturing/Document/ProdOrderRoutingLine.Table.al`
  - `App/Layers/IT/BaseApp/Manufacturing/Document/ProdOrderRoutingLine.Table.al`
- No other layers keep a copy of this table, so exactly two files change.
