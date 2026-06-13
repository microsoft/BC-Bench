codeunit 50240 "Perf Sample Trigger Param Good"
{
    procedure BulkFlagOrders(var SalesHeader: Record "Sales Header")
    begin
        if SalesHeader.FindSet(true) then
            repeat
                SalesHeader."Job Queue Status" := SalesHeader."Job Queue Status"::"Scheduled for Posting";
                // Trigger has nothing to add for a status flip in this code path.
                SalesHeader.Modify(false);
            until SalesHeader.Next() = 0;
    end;

    procedure CreateOrder(var SalesHeader: Record "Sales Header"; CustomerNo: Code[20])
    begin
        SalesHeader.Init();
        SalesHeader."Document Type" := SalesHeader."Document Type"::Order;
        SalesHeader."Sell-to Customer No." := CustomerNo;
        // OnInsert allocates the No.-Series number — the trigger is required.
        SalesHeader.Insert(true);
    end;
}
