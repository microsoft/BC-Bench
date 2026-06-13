codeunit 50239 "Perf Sample PromptInTxn Bad"
{
    procedure PostOrder(DocNo: Code[20])
    var
        SalesHeader: Record "Sales Header";
        PostConfirmQst: Label 'Post this order?';
    begin
        SalesHeader.LockTable();
        SalesHeader.Get(SalesHeader."Document Type"::Order, DocNo);
        // Lock held while the dialog is on screen — minutes or hours.
        if Confirm(PostConfirmQst) then
            PostSalesOrder(SalesHeader);
    end;

    local procedure PostSalesOrder(var SalesHeader: Record "Sales Header")
    begin
    end;
}
