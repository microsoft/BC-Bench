# [W1][Report][7304][Get Outbound Source Documents] OnBeforeIsPickToBeMadeForAsmLine event

### Why do you need this change?

We need to be able to override the IsPickToBeMadeForAsmLine logic for assembly-to-order lines.
Our extension handles a custom pick scenario where the standard logic incorrectly includes or
excludes Assemble to Order lines.

### Describe the request

Report 7304 - Get Outbound Source Documents
Procedure: IsPickToBeMadeForAsmLine

We need an integration event that's triggered inside this function before the code runs.  The function would then Exit(Result) if IsHandled = true.

[IntegrationEvent(false, false)]
local procedure OnBeforeIsPickToBeMadeForAsmLine(AsmLine: Record "Assembly Line"; var Result: Boolean; var IsHandled: Boolean)
begin
end;
