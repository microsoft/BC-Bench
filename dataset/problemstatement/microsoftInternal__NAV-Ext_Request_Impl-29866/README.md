# [Event Request] - codeunit 23 "Item Jnl.-Post Batch"

### Why do you need this change?

Please add a new integration event with an `IsHandled` parameter in the `PostLines` procedure of codeunit 23 "Item Jnl.-Post Batch", immediately before the `ItemJnlLine.TestField("Document No.", ...)` call that validates the document number against the No. Series.

This event is needed to allow extensions to conditionally bypass the document number sequence validation for specific journal templates and batches where manual document numbering is intentionally permitted for example, a returns journal where users must enter the original source document number instead of receiving an auto-assigned number from the series.

---

### Alternatives Evaluated

The following events in codeunit 23 "Item Jnl.-Post Batch" were considered as alternatives within the `PostLines` procedure:

- **`OnBeforePostLines`**: Fires before the repeat loop begins. Individual `ItemJnlLine` records have not yet been iterated at this point, so per-line conditions such as `"Document No."` and `"Posting Date"` are not yet available. This event cannot be used.

- **`OnPostLinesOnBeforePostLine`**: Fires after the document number validation has already executed. The `TestField` call will have already run and may have already raised an error before this event is reached, making it impossible to conditionally prevent the validation.

None of the existing events provide the correct insertion point we need.

---

### Performance Considerations

The `PostLines` procedure iterates once per journal line during a user-initiated posting action. The overhead of firing an integration event per line is negligible and consistent with the performance profile of all other event publishers in the same loop (e.g., `OnPostLinesOnBeforePostLine`, `OnBeforePostJnlLine`, `OnPostLinesOnAfterPostLine`). When no subscriber sets `IsHandled := true`, the standard validation executes unchanged.

---

## Data Sensitivity Review

The event parameters do not expose any sensitive or confidential data. `ItemJnlLine` (Record "Item Journal Line"), `ItemJnlBatch` (Record "Item Journal Batch"), and `LastDocNo2` are already parameters or local variables within the `PostLines` procedure and are not introducing any additional data exposure.

The `IsHandled` parameter is required because without it, the standard `TestField` call would still execute regardless of what a subscriber does, making the event non-functional for this use case.

`LastDocNo2` is included as a read-only parameter so that subscribers can evaluate the current document tracking state for example, to check whether `"Document No." <> LastDocNo2` before deciding whether to set `IsHandled`. The `LastDocNo2` update always happens unconditionally after the event, so subscribers do not need to maintain it themselves.

---

### Multi-Extension Interaction

Multiple extensions can safely subscribe to this event. If any subscriber sets `IsHandled := true`, the standard `TestField` validation is suppressed for that line.

---

### Describe the request

**Requested event placement in `PostLines`:**

```al
local procedure PostLines(var ItemJnlLine: Record "Item Journal Line"; var PhysInvtCountMgt: Codeunit "Phys. Invt. Count.-Management")
var
    TempTrackingSpecification: Record "Tracking Specification" temporary;
    ItemJnlLineLoop: Record "Item Journal Line";
    OriginalQuantity: Decimal;
    OriginalQuantityBase: Decimal;
    IsHandled: Boolean;
begin
    OnBeforePostLines(ItemJnlLine, ItemRegNo, WhseRegNo);

    LastDocNo := '';
    LastDocNo2 := '';
    LastPostedDocNo := '';

    ItemJnlLineLoop.Copy(ItemJnlLine);
    // ...
    ItemJnlLineLoop.FindSet();
    repeat
        ItemJnlLine := ItemJnlLineLoop;

        //>> code change start
        IsHandled := false;
        OnBeforeValidateDocumentNo(ItemJnlLine, ItemJnlBatch, LastDocNo2, IsHandled);
        if not IsHandled then
        //<< code change end
            if not ItemJnlLine.EmptyLine() and (ItemJnlBatch."No. Series" <> '') and (ItemJnlLine."Document No." <> LastDocNo2) then
                ItemJnlLine.TestField("Document No.", NoSeriesBatch.GetNextNo(ItemJnlBatch."No. Series", ItemJnlLine."Posting Date"));
        if not ItemJnlLine.EmptyLine() then
            LastDocNo2 := ItemJnlLine."Document No.";

        // ... rest of procedure unchanged
    until ItemJnlLineLoop.Next() = 0;

    OnAfterPostLines(ItemJnlLine, ItemRegNo, WhseRegNo);
end;
```

---

## Event Signature

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeValidateDocumentNo(var ItemJnlLine: Record "Item Journal Line"; var ItemJnlBatch: Record "Item Journal Batch"; LastDocNo2: Code[20]; var IsHandled: Boolean)
begin
end;
```
