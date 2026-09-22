# [Event Request] Codeunit 80 "Sales-Post" - CreatePrepaymentLines procedure

### Why do you need this change?

Dear support, in **codeunit 80 "Sales-Post"** we need to add an event to insert additional records into the `TempPrepmtSalesLine` buffer before moving on to the next `TempSalesLine`.

The customer had a custom in NAV that inserts additional records into the `TempPrepmtSalesLine` table based on data contained in the `TempSalesLine` table.
The other events won't work because I don't have access to all the necessary variables.

(I modified the event by adding `NextLineNo` as a paramete passed by reference, I'll need it for the new lines that will be created)

Another solution could be to add `TempSalesLine` as a parameter to the `OnCreatePrepaymentLinesOnAfterProcessSalesLines` event so that it can loop through the cycle again and execute the custom, but of course this would incur additional computational overhead.

### Describe the request

	[IntegrationEvent(false, false)]
    local procedure OnCreatePrepaymentLinesOnAfterTempPrepmtSalesLineInsertOrModify(var TempPrepmtSalesLine: Record "Sales Line" temporary; SalesHeader: Record "Sales Header"; var TempSalesLine: Record "Sales Line" temporary, var NextLineNo: Integer)
    begin
    end;

[Changes between **]

	procedure CreatePrepaymentLines(SalesHeader: Record "Sales Header"; CompleteFunctionality: Boolean)
	...
	                if TempLineFound then begin
                        PrepmtAmtToDeduct :=
                          TempPrepmtSalesLine."Prepmt Amt to Deduct" +
                          InsertedPrepmtVATBaseToDeduct(
                            SalesHeader, TempSalesLine, TempPrepmtSalesLine."Line No.", TempPrepmtSalesLine."Unit Price");
                        VATDifference := TempPrepmtSalesLine."VAT Difference";
                        TempPrepmtSalesLine.Validate(
                          "Unit Price", TempPrepmtSalesLine."Unit Price" + TempSalesLine."Prepmt Amt to Deduct");
                        TempPrepmtSalesLine.Validate("VAT Difference", VATDifference - TempSalesLine."Prepmt VAT Diff. to Deduct");
                        TempPrepmtSalesLine."Prepmt Amt to Deduct" := PrepmtAmtToDeduct;
                        if TempSalesLine."Prepayment %" < TempPrepmtSalesLine."Prepayment %" then
                            TempPrepmtSalesLine."Prepayment %" := TempSalesLine."Prepayment %";
                        OnBeforeTempPrepmtSalesLineModify(TempPrepmtSalesLine, TempSalesLine, SalesHeader, CompleteFunctionality);
                        TempPrepmtSalesLine.Modify();
                    end else begin
                        TempPrepmtSalesLine.Init();
                        TempPrepmtSalesLine."Document Type" := SalesHeader."Document Type";
                        TempPrepmtSalesLine."Document No." := SalesHeader."No.";
                        TempPrepmtSalesLine."Line No." := 0;
                        TempPrepmtSalesLine."System-Created Entry" := true;
                        OnCreatePrepaymentLinesOnBeforeValidateType(TempPrepmtSalesLine, SalesHeader, TempSalesLine);
                        if CompleteFunctionality then
                            TempPrepmtSalesLine.Validate(Type, TempPrepmtSalesLine.Type::"G/L Account")
                        else
                            TempPrepmtSalesLine.Type := TempPrepmtSalesLine.Type::"G/L Account";
                        // deduct from prepayment
                        TempPrepmtSalesLine.Validate("No.", GLAcc."No.");
                        TempPrepmtSalesLine.Validate(Quantity, -1);
                        TempPrepmtSalesLine."Qty. to Ship" := TempPrepmtSalesLine.Quantity;
                        TempPrepmtSalesLine."Qty. to Invoice" := TempPrepmtSalesLine.Quantity;
                        OnCreatePrepaymentLinesOnBeforeInsertedPrepmtVATBaseToDeduct(TempPrepmtSalesLine, SalesHeader, TempSalesLine);
                        PrepmtAmtToDeduct := InsertedPrepmtVATBaseToDeduct(SalesHeader, TempSalesLine, NextLineNo, 0);
                        TempPrepmtSalesLine.Validate("Unit Price", TempSalesLine."Prepmt Amt to Deduct");
                        TempPrepmtSalesLine.Validate("VAT Difference", -TempSalesLine."Prepmt VAT Diff. to Deduct");
                        TempPrepmtSalesLine."Prepmt Amt to Deduct" := PrepmtAmtToDeduct;
                        TempPrepmtSalesLine."Prepayment %" := TempSalesLine."Prepayment %";
                        TempPrepmtSalesLine."Prepayment Line" := true;
                        TempPrepmtSalesLine."Include in VAT Transac. Rep." := not TempPrepmtSalesLine."Prepayment Line";
                        TempPrepmtSalesLine."Shortcut Dimension 1 Code" := TempSalesLine."Shortcut Dimension 1 Code";
                        TempPrepmtSalesLine."Shortcut Dimension 2 Code" := TempSalesLine."Shortcut Dimension 2 Code";
                        TempPrepmtSalesLine."Dimension Set ID" := TempSalesLine."Dimension Set ID";
                        TempPrepmtSalesLine."Line No." := NextLineNo;
                        NextLineNo := NextLineNo + 10000;
                        OnBeforeTempPrepmtSalesLineInsert(TempPrepmtSalesLine, TempSalesLine, SalesHeader, CompleteFunctionality);
                        TempPrepmtSalesLine.Insert();

                        IsHandled := false;
                        OnBeforeCreatePrepaymentTextLines(TempPrepmtSalesLine, TempSalesLine, SalesHeader, CompleteFunctionality, IsHandled);
                        if not IsHandled then
                            TransferExtText.PrepmtGetAnyExtText(
                                TempPrepmtSalesLine."No.", DATABASE::"Sales Invoice Line",
                                SalesHeader."Document Date", SalesHeader."Language Code", TempExtTextLine);
                        if TempExtTextLine.Find('-') then
                            repeat
                                TempPrepmtSalesLine.Init();
                                TempPrepmtSalesLine.Description := TempExtTextLine.Text;
                                TempPrepmtSalesLine."System-Created Entry" := true;
                                TempPrepmtSalesLine."Prepayment Line" := true;
                                TempPrepmtSalesLine."Line No." := NextLineNo;
                                NextLineNo := NextLineNo + 10000;
                                OnCreatePrepaymentLinesOnBeforeInsertTempLineForExtText(TempPrepmtSalesLine, TempSalesLine, TempExtTextLine, SalesHeader);
                                TempPrepmtSalesLine.Insert();
                            until TempExtTextLine.Next() = 0;
                    end;
					** OnCreatePrepaymentLinesOnAfterTempPrepmtSalesLineInsertOrModify(TempPrepmtSalesLine, SalesHeader, TempSalesLine, NextLineNo); **
                end;
            until TempSalesLine.Next() = 0;
            OnCreatePrepaymentLinesOnAfterProcessSalesLines(SalesHeader, TempPrepmtSalesLine, NextLineNo);
        end;
        DividePrepmtAmountLCY(TempPrepmtSalesLine, SalesHeader);
        if TempPrepmtSalesLine.FindSet() then
            repeat
                TempSalesLineGlobal := TempPrepmtSalesLine;
                TempSalesLineGlobal.Insert();
            until TempPrepmtSalesLine.Next() = 0;
    end;
