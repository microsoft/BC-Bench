# [Extensibility Request] codeunit 5813 "Undo Purchase Receipt Line" add event OnBeforeFindPostedWhseRcptLine

### Why do you need this change?

In 4PS Construct, we need to extend the undo purchase receipt flow in local procedure "Code" so that the decision to call WhseUndoQty.FindPostedWhseRcptLine can depend not only on Type = Item, but also on additional line-specific conditions such as whether the field "Job No." is empty.

In our scenario, the standard condition is too restrictive because it only checks whether PurchRcptLine.Type = PurchRcptLine.Type::Item. For our customization, this causes the warehouse receipt lookup to run in cases where it should be skipped.

We need to control that decision before WhseUndoQty.FindPostedWhseRcptLine is called, because that choice affects the remainder of the line processing, including whether PostItemJnlLine is executed in that branch or whether DocLineNo is assigned through GetCorrectionLineNo(PurchRcptLine).

There is already an existing event in WhseUndoQuantity.Codeunit.al named OnBeforeFindPostedWhseRcptLine, but it is not sufficient for this scenario. That event is raised inside FindPostedWhseRcptLine after the standard caller has already decided to enter that path, and it does not provide PurchRcptLine. Because of that, it cannot be used to evaluate our custom condition before the branch is chosen.

We understand that the requested event would be raised inside the repeat..until loop in local procedure "Code". In our view, this is necessary because the decision is line-specific and must be evaluated for each PurchRcptLine individually.

This feature was previously requested https://github.com/microsoft/ALAppExtensions/issues/29910 but was closed due to inactivity.

### Describe the request

On behalf of 4PS, I would like to request to add integration event OnBeforeFindPostedWhseRcptLine before WhseUndoQty.FindPostedWhseRcptLine invoke and ShouldFindPostedWhseRcptLine boolean to be able change condition related to our customization.

    local procedure "Code"()
        var
            PostedWhseRcptLine: Record "Posted Whse. Receipt Line";
            PurchLine: Record "Purchase Line";
            Window: Dialog;
            ItemRcptEntryNo: Integer;
            DocLineNo: Integer;
            PostedWhseRcptLineFound: Boolean;
            ShouldFindPostedWhseRcptLine: Boolean; //new
        begin
            OnBeforeCode(PurchRcptLine, UndoPostingMgt);

            CheckPurchRcptLines(PurchRcptLine, Window);

            BindSubscription(this);
            PurchRcptLine.Find('-');
            OnCodeOnBeforeLoopPurchRcptLine(PurchRcptLine);
            repeat
                TempGlobalItemLedgEntry.Reset();
                if not TempGlobalItemLedgEntry.IsEmpty() then
                    TempGlobalItemLedgEntry.DeleteAll();
                TempGlobalItemEntryRelation.Reset();
                if not TempGlobalItemEntryRelation.IsEmpty() then
                    TempGlobalItemEntryRelation.DeleteAll();

                if not HideDialog then
                    Window.Open(Text001);

                ShouldFindPostedWhseRcptLine := PurchRcptLine.Type = PurchRcptLine.Type::Item; //new
                OnBeforeFindPostedWhseRcptLine(PurchRcptLine, ShouldFindPostedWhseRcptLine); //new
                if ShouldFindPostedWhseRcptLine then begin //new
                    PostedWhseRcptLineFound :=
                    WhseUndoQty.FindPostedWhseRcptLine(
                        PostedWhseRcptLine,
                        DATABASE::"Purch. Rcpt. Line",
                        PurchRcptLine."Document No.",
                        DATABASE::"Purchase Line",
                        PurchLine."Document Type"::Order.AsInteger(),
                        PurchRcptLine."Order No.",
                        PurchRcptLine."Order Line No.");

                    ItemRcptEntryNo := PostItemJnlLine(PurchRcptLine, DocLineNo);
                end else
                    DocLineNo := GetCorrectionLineNo(PurchRcptLine);

                InsertNewReceiptLine(PurchRcptLine, ItemRcptEntryNo, DocLineNo);
                OnAfterInsertNewReceiptLine(PurchRcptLine, PostedWhseRcptLine, PostedWhseRcptLineFound, DocLineNo, PostedWhseRcptLine);

                if PostedWhseRcptLineFound then
                    WhseUndoQty.UndoPostedWhseRcptLine(PostedWhseRcptLine);

                UpdateOrderLine(PurchRcptLine);
                if PostedWhseRcptLineFound then
                    WhseUndoQty.UpdateRcptSourceDocLines(PostedWhseRcptLine);

                if (PurchRcptLine."Blanket Order No." <> '') and (PurchRcptLine."Blanket Order Line No." <> 0) then
                    UpdateBlanketOrder(PurchRcptLine);

                PurchRcptLine."Quantity Invoiced" := PurchRcptLine.Quantity;
                PurchRcptLine."Qty. Invoiced (Base)" := PurchRcptLine."Quantity (Base)";
                PurchRcptLine."Qty. Rcd. Not Invoiced" := 0;
                PurchRcptLine.Correction := true;

                OnBeforePurchRcptLineModify(PurchRcptLine, TempWhseJnlLine);
                PurchRcptLine.Modify();
                OnAfterPurchRcptLineModify(PurchRcptLine, TempWhseJnlLine, DocLineNo, UndoPostingMgt);

                if not JobItem then
                    JobItem := (PurchRcptLine.Type = PurchRcptLine.Type::Item) and (PurchRcptLine."Job No." <> '');
            until PurchRcptLine.Next() = 0;
            UnbindSubscription(this);

            OnCodeOnBeforeMakeInventoryAdjustment(PurchLine, PurchRcptLine);
            MakeInventoryAdjustment();

            WhseUndoQty.PostTempWhseJnlLine(TempWhseJnlLine);

            OnAfterCode(PurchRcptLine, UndoPostingMgt);
        end;


    [IntegrationEvent(false, false)]
    local procedure OnBeforeFindPostedWhseRcptLine(PurchRcptLine: Record "Purch. Rcpt. Line"; var ShouldFindPostedWhseRcptLine: Boolean)
    begin
    end;
