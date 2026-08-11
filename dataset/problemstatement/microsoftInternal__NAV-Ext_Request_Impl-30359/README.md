# Extensibility request: add a Direction parameter to OnBeforeScheduleRoutingLine in codeunit 99000774 "Calculate Routing Line"

## Why do you need this change?

We want to modify the behaviour of starting- and ending-datetime calculation in production order routing.
Therefore we need the parameter `Direction` as a `var` parameter in the parameter list of an existing
publisher event.

## Describe the request

In codeunit 99000774 "Calculate Routing Line", in the scheduling logic, add `Direction` as a `var`
parameter to the publisher `OnBeforeScheduleRoutingLine`, and pass it where the event is raised:

```al
IsHandled := false;
OnBeforeScheduleRoutingLine(ProdOrderRoutingLine, CalcStartEndDate, IsHandled, Direction);
if not IsHandled then
    if ProdOrderRoutingLine."Schedule Manually" then
        CalculateRoutingLineFixed()
    else
        if Direction = Direction::Backward then
            CalcRoutingLineBack(CalcStartEndDate)
        else
            CalcRoutingLineForward(CalcStartEndDate);
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeScheduleRoutingLine(var ProdOrderRoutingLine: Record "Prod. Order Routing Line"; var CalcStartEndDate: Boolean; var IsHandled: Boolean; var Direction: Option Forward,Backward)
begin
end;
```

## Scope

- File: `CalculateRoutingLine.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
