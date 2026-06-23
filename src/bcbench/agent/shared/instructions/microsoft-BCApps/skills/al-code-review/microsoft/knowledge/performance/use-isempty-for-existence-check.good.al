codeunit 50212 "Perf Sample IsEmpty Good"
{
    procedure HasOpenSalesOrders(CustomerNo: Code[20]): Boolean
    var
        SalesHeader: Record "Sales Header";
    begin
        SalesHeader.SetRange("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.SetRange("Sell-to Customer No.", CustomerNo);
        exit(not SalesHeader.IsEmpty());
    end;
}
