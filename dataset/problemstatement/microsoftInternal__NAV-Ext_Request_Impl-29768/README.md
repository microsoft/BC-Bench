# [Extensibility Request] Report 5900 Service Order - Set global codeunit-var FormatDocument to protected

### Why do you need this change?

I need to align the capabilities of the service order and the sales order via ReportExtension. I want to use same pattern as in sales order to fill PaymentMethodDescription , ShipmentMethodDescription, etc. by using FormatDocument.SetTotalLabels() or SetPayment/Shipment/*Method.

### Describe the request

In Report move this var into protected var
FormatDocument: Codeunit "Format Document";
