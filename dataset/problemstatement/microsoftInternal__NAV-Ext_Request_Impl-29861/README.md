# Event request [W1][Codeunit][816]["Purch. Post Invoice"] OnSplitFAOnBeforeRunGenJnlPostLine event

### Why do you need this change?

We have additional amounts in the "Gen. Journal Line" table that need to be divided when creating multiple FA cards on a purchase invoice.

### Describe the request

We suggest new event OnSplitFAOnBeforeRunGenJnlPostLine in the SplitFA procedure.
```
...
        CalcSplitAmount(
            GenJnlLine."VAT Difference", GenJnlLine2."VAT Difference", TotalGenJnlLine."VAT Difference", I, SplitNo);
        CalcSplitAmount(
            GenJnlLine."Salvage Value", GenJnlLine2."Salvage Value", TotalGenJnlLine."Salvage Value", I, SplitNo);

        //new integration event
        OnSplitFAOnBeforeRunGenJnlPostLine(GenJnlLine, GenJnlLine2, TotalGenJnlLine, I, SplitNo);

        RunGenJnlPostLine(GenJnlLine, GenJnlPostLine);
    end;
end;
...
[IntegrationEvent(false, false)]
local procedure OnSplitFAOnBeforeRunGenJnlPostLine(var GenJnlLine: Record "Gen. Journal Line"; var GenJnlLine2: Record "Gen. Journal Line"; var TotalGenJnlLine: Record "Gen. Journal Line"; I: Integer; SplitNo: Integer)
begin
end;
```
