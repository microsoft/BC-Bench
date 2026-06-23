codeunit 50209 "Sample Named Invocations Bad"
{
    procedure ShowShipmentLines(var SalesShptLine: Record "Sales Shipment Line")
    begin
        Page.RunModal(525, SalesShptLine);
    end;

    procedure RunInvoiceReport()
    begin
        Report.Run(206, true);
    end;
}
