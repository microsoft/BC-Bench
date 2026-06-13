codeunit 50238 "Perf Sample PromptInTxn Good"
{
    procedure PostOrder(DocNo: Code[20])
    var
        SalesHeader: Record "Sales Header";
        PostConfirmQst: Label 'Post this order?';
    begin
        if not Confirm(PostConfirmQst) then
            exit;
        SalesHeader.LockTable();
        SalesHeader.Get(SalesHeader."Document Type"::Order, DocNo);
        PostSalesOrder(SalesHeader);
    end;

    local procedure PostSalesOrder(var SalesHeader: Record "Sales Header")
    begin
    end;
}
