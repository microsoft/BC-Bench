# [Event Request] codeunit 905 "Assembly Line Management" procedure ShowAvailability()

### Why do you need this change?

In certain circumstances I want to be able to either skip showing the availability page when the QtyAvailToLow is true and/or the ShowPageEvenIfEnoughComponentsAvailable is true. In other circumstances I want to show an error when the QtyAvailToLow is true and/or the ShowPageEvenIfEnoughComponentsAvailable is true.

I've tried using the OnBeforeShowAvailability() event at the start but can't achieve what I want because I would need to call the CopyInventoriableItemAsmLines and AvailToPromise procedures in order to calculate QtyAvailTooLow, but they are currently local.  I have also tried replicating them but I can't because AvailToPromise calls other procedures which are local.


### Describe the request

Please can you add the following event/code after the QtyAvailTooLow boolean field has been set...

```
OnAfterQtyAvailTooLowCalculated(TempAssemblyHeader, TempAssemblyLine, ShowPageEvenIfEnoughComponentsAvailable, IsHandled, Rollback, WarningModeOff);
if IsHandled then
    exit(Rollback);

```
The event publisher would be...

```
[IntegrationEvent(false, false)]
local procedure OnAfterQtyAvailTooLowCalculated(var TempAssemblyHeader: Record "Assembly Header" temporary; var TempAssemblyLine: Record "Assembly Line" temporary; ShowPageEvenIfEnoughComponentsAvailable: Boolean; var IsHandled: Boolean; var RollBack: Boolean; WarningModeOff: Boolean)
begin
end;
```
