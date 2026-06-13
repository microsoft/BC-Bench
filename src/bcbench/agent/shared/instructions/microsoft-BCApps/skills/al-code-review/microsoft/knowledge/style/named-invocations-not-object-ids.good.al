codeunit 50208 "Sample Named Invocations Good"
{
    procedure ShowShipmentLines(var SalesShptLine: Record "Sales Shipment Line")
    begin
        Page.RunModal(Page::"Posted Sales Shipment Lines", SalesShptLine);
    end;

    procedure RunInvoiceReport()
    begin
        Report.Run(Report::"Sales - Invoice", true);
    end;
}
