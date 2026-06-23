codeunit 50213 "Perf Sample IsEmpty Bad"
{
    procedure HasOpenSalesOrders(CustomerNo: Code[20]): Boolean
    var
        SalesHeader: Record "Sales Header";
    begin
        SalesHeader.SetRange("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.SetRange("Sell-to Customer No.", CustomerNo);
        // Count materializes a count the caller does not need.
        if SalesHeader.Count() > 0 then
            exit(true);
        // FindFirst materializes a row the caller throws away.
        if SalesHeader.FindFirst() then
            exit(true);
        exit(false);
    end;
}
