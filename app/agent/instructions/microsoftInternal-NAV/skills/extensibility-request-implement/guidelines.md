# Extension fix guidelines

These guidelines supplement the repository-wide rules in `.github/copilot/code-guidelines.md`.
When fixing AL extensibility issues, follow the event-specific rules in this file in addition to
general AL best practices.

## Event syntax

### Integration event declaration

```al
[IntegrationEvent(IncludeSender: Boolean, GlobalVarAccess: Boolean)]
local procedure EventName(Parameters)
begin
end;
```

**Parameters:**

- `IncludeSender`: Usually `false`. Set to `true` only when subscribers need the sender object.
- `GlobalVarAccess`: Usually `false`. Set to `true` only when subscribers must access globals.

### Event publisher pattern

```al
local procedure DoSomething(var SalesHeader: Record "Sales Header")
var
	IsHandled: Boolean;
begin
	IsHandled := false;
	OnBeforeDoSomething(SalesHeader, IsHandled);
	if IsHandled then
		exit;

	// Standard logic here

	OnAfterDoSomething(SalesHeader);
end;
```

## Naming conventions

### Event name format

All events must follow the standard naming pattern based on where they are raised, regardless of
any suggested name.

**Pattern components:**

- Prefix: Always `On`
- Procedure or trigger name: The containing procedure or trigger
- Timing: `OnBefore` or `OnAfter`
- Action context: The specific action when the event is in the middle of the flow

### Events at the beginning or end of a procedure or trigger

Use `OnBefore[ProcedureOrTriggerName]` or `OnAfter[ProcedureOrTriggerName]` when the event fires
at the very start or very end.

| Location | Event name |
|----------|------------|
| `PostSalesLine` procedure, beginning | `OnBeforePostSalesLine` |
| `PostSalesLine` procedure, end | `OnAfterPostSalesLine` |
| `OnInsert` trigger, beginning | `OnBeforeOnInsert` |
| `OnModify` trigger, end | `OnAfterOnModify` |
| `Sell-to Customer No.` `OnValidate`, beginning | `OnBeforeValidateSellToCustomerNo` |
| `Quantity` `OnValidate`, end | `OnAfterValidateQuantity` |

```al
procedure PostSalesLine(var SalesLine: Record "Sales Line")
begin
	OnBeforePostSalesLine(SalesLine);

	ValidateLine(SalesLine);
	CalculateAmounts(SalesLine);
	InsertEntries(SalesLine);

	OnAfterPostSalesLine(SalesLine);
end;
```

### Events in the middle of a procedure or trigger

Use `On[ProcedureOrTriggerName]OnBefore[ActionContext]` or
`On[ProcedureOrTriggerName]OnAfter[ActionContext]` when the event is raised around a specific step
inside the flow.

| Location | Event name |
|----------|------------|
| `PostSalesLine` before validation | `OnPostSalesLineOnBeforeValidateLine` |
| `PostSalesLine` after calculation | `OnPostSalesLineOnAfterCalculateAmounts` |
| `Code` procedure before check | `OnCodeOnBeforeCheck` |
| `OnInsert` after init defaults | `OnOnInsertOnAfterInitDefaults` |
| `OnModify` before location validation | `OnOnModifyOnBeforeValidateLocationCode` |

```al
procedure PostSalesLine(var SalesLine: Record "Sales Line")
begin
	OnPostSalesLineOnBeforeValidateLine(SalesLine);
	ValidateLine(SalesLine);

	OnPostSalesLineOnAfterValidateLine(SalesLine);

	CalculateAmounts(SalesLine);

	OnPostSalesLineOnAfterCalculateAmounts(SalesLine);

	InsertEntries(SalesLine);
end;
```

### Naming examples

Incorrect:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePost(var SalesLine: Record "Sales Line")
begin
end;
```

Correct:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePostSalesLine(var SalesLine: Record "Sales Line")
begin
end;

[IntegrationEvent(false, false)]
local procedure OnPostSalesLineOnBeforeValidation(var SalesLine: Record "Sales Line")
begin
end;
```

### Quick reference

- Beginning or end: `OnBefore` or `OnAfter` + procedure or trigger name
- Middle of flow: `On` + procedure or trigger name + `OnBefore` or `OnAfter` + action context

## Event parameter naming

### Record parameters

Use the AL table name with spaces removed. Do not abbreviate record parameter names.

| Table name | Correct parameter | Avoid |
|------------|-------------------|-------|
| `Sales Header` | `SalesHeader` | `SalesHdr`, `SH` |
| `Sales Line` | `SalesLine` | `SalesLn`, `SL` |
| `Item Ledger Entry` | `ItemLedgerEntry` | `ItemLedgEntry`, `ILE` |
| `G/L Entry` | `GLEntry` | `GLE`, `GenLedgEntry` |
| `Purchase Header` | `PurchaseHeader` | `PurchHdr`, `PH` |
| `Customer` | `Customer` | `Cust`, `C` |
| `Vendor` | `Vendor` | `Vend`, `V` |

Incorrect:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePost(var SalesHdr: Record "Sales Header"; var ItemLedgEntry: Record "Item Ledger Entry")
begin
end;
```

Correct:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePost(var SalesHeader: Record "Sales Header"; var ItemLedgerEntry: Record "Item Ledger Entry")
begin
end;
```

### Simple type parameters

Use descriptive names for simple types. Do not abbreviate them.

| Avoid | Correct |
|-------|---------|
| `DocNo` | `DocumentNo` |
| `Amt` | `Amount` or `TotalAmount` |
| `Qty` | `Quantity` |
| `Desc` | `Description` |
| `Date` | `PostingDate`, `DocumentDate`, or another precise name |

Incorrect:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePost(DocNo: Code[20]; Amt: Decimal; Qty: Decimal)
begin
end;
```

Correct:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePost(DocumentNo: Code[20]; TotalAmount: Decimal; Quantity: Decimal)
begin
end;
```

### Temporary record parameters

All temporary record parameters in event signatures must use the `Temp` prefix.

Rationale:

- It makes the temporary nature explicit to subscribers.
- It prevents confusion about persistence.
- It follows standard BC naming conventions.

Incorrect:

```al
[IntegrationEvent(false, false)]
local procedure OnAfterProcess(var InvtOrderTracking: Record "Invt. Order Tracking" temporary)
begin
end;
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeCalculate(var Buffer: Record Item temporary)
begin
end;
```

Correct:

```al
[IntegrationEvent(false, false)]
local procedure OnAfterProcess(var TempInvtOrderTracking: Record "Invt. Order Tracking" temporary)
begin
end;
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeCalculate(var TempItem: Record Item temporary)
begin
end;
```

Common temporary prefixes:

- `TempBuffer`
- `TempItem`
- `TempCustomer`
- `TempInteger`

## Signature changes

### New parameters go at the end

When adding a parameter to an existing event, always append it at the end of the signature.

Original event:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeProcess(var Customer: Record Customer; var IsHandled: Boolean)
begin
end;
```

Incorrect:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeProcess(var Customer: Record Customer; NewParam: Text; var IsHandled: Boolean)
begin
end;
```

Correct:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeProcess(var Customer: Record Customer; var IsHandled: Boolean; NewParam: Text)
begin
end;
```

## IsHandled rules

### Always initialize `IsHandled`

When adding an event with `IsHandled`, or when adding `IsHandled` to an existing event, set it to
`false` before calling the event.

Correct:

```al
procedure PostDocument(var SalesHeader: Record "Sales Header")
var
	IsHandled: Boolean;
begin
	IsHandled := false;
	OnBeforePostDocument(SalesHeader, IsHandled);
	if IsHandled then
		exit;

	// Standard logic
end;
```

Incorrect:

```al
procedure PostDocument(var SalesHeader: Record "Sales Header")
var
	IsHandled: Boolean;
begin
	OnBeforePostDocument(SalesHeader, IsHandled);
	if IsHandled then
		exit;

	// Standard logic
end;
```

### Adding `IsHandled` to an existing event

Before:

```al
procedure Process(var Customer: Record Customer)
begin
	OnBeforeProcess(Customer);
	// Standard logic
end;

[IntegrationEvent(false, false)]
local procedure OnBeforeProcess(var Customer: Record Customer)
begin
end;
```

After:

```al
procedure Process(var Customer: Record Customer)
var
	IsHandled: Boolean;
begin
	IsHandled := false;
	OnBeforeProcess(Customer, IsHandled);
	if IsHandled then
		exit;

	// Standard logic
end;

[IntegrationEvent(false, false)]
local procedure OnBeforeProcess(var Customer: Record Customer; var IsHandled: Boolean)
begin
end;
```

## Review checklist

Use this checklist when adding or reviewing AL extensibility events:

- Event name matches its exact placement in the procedure or trigger.
- Record parameters use full table names with spaces removed.
- Temporary record parameters use the `Temp` prefix.
- Simple parameters use descriptive, non-abbreviated names.
- New parameters are appended at the end of existing signatures.
- `IsHandled` is explicitly initialized to `false` before the event call.
- `IncludeSender` and `GlobalVarAccess` stay `false` unless there is a concrete need.
