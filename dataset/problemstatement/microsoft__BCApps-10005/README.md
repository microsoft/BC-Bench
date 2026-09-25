# Undo Return Shipment from a line of type Comment is misleading

## Repro Steps

Create a Purchase Return Order for Fabrikam, by using Copy Document from Posted Receipt 107207.
Post it as "Ship".
Go to the Posted Return Shipment and notice that the first line - of type Comment - is selected.
Click Functions - Undo Return Shipment. This is what you get:
![image.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/46538dbf-2eb4-4a1d-8277-59a135b3e5aa?fileName=image.png)
![image.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/03dcac1e-5f9d-47ac-99c1-b3f1630a90a7?fileName=image.png)
This is misleading as the shipment was not actually reversed. In this case I would expect an error message saying that they need to select a line that can actually be returned, not a comment (or make the Undo Return Shipment button disabled for that line).
In my case the AI agent I built, going through this scenario, was "told" that the document had already been reversed and it threw my agent off its course. Had it received a different error message, e.g. to select the lines they want to reverse, it would proceed in its course.
If requesting support, please provide the following details to help troubleshooting:
Error message:
This return shipment has already been reversed.
Internal session ID:
5d2e92b6-d981-4e5d-a700-b5c3519ea646
Application Insights session ID:
b566fef9-7f28-4f51-9d68-562eb32d6ba3
Client activity id:
a2103692-176c-4782-8213-0188e9a210aa
Time stamp on error:
2026-07-27T15:07:49.0703254Z
User telemetry id:
3353863b-12be-4f21-b7e5-04e004be89dd
AL call stack:
"Undo Return Shipment Line"(CodeUnit 5814).Code line 14 - Base Application by Microsoft version 29.0.52778.6247
"Undo Return Shipment Line"(CodeUnit 5814).OnRun(Trigger) line 16 - Base Application by Microsoft version 29.0.52778.6247
"Posted Return Shipment Subform"(Page 6651).UndoReturnShipment line 6 - Base Application by Microsoft version 29.0.52778.6247
"Posted Return Shipment Subform"(Page 6651)."&Undo Return Shipment - OnAction"(Trigger) line 2 - Base Application by Microsoft version 29.0.52778.6247
