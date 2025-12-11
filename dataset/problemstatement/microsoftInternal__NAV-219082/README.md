# Title: Error "An error occurred and the transaction is stopped. Contact your administrator or partner for further assistance." when printing a service order with work description from the service order card page.
## Repro Steps:
Reported in SE environment.
Happens in W1 as well
Tested in NL 26.2
Open the Company Information and change the User Experience to Premium
1. Go to service order page
2. Create a new service order
3. Enter No. Series
   Enter description = New
   Customer No. = 10000
   Work Description = Test
4. Enter service line
   Item No. = 1896-S
5. Click print
   The error "An error occurred, and the transaction is stopped. Contact your administrator or partner for further assistance." is thrown.
Error call stack

If requesting support, please provide the following details to help troubleshooting:
Error message:
An error occurred and the transaction is stopped. Contact your administrator or partner for further assistance.
The following AL methods are limited during write transactions because one or more tables will be locked: Form.RunModal, Codeunit.Run, Report.RunModal, XmlPort.RunModal.
Form.RunModal is not allowed in write transactions.
Codeunit.Run is allowed in write transactions only if the return value is not used. For example, 'OK := Codeunit.Run()' is not allowed.
Report.RunModal is allowed in write transactions only if 'RequestForm = false'. For example, 'Report.RunModal(...,false)' is allowed.
XmlPort.RunModal is allowed in write transactions only if 'RequestForm = false'. For example, 'XmlPort.RunModal(...,false)' is allowed.
Use the commit method to save the changes before this call, or structure the code differently.
Contact your application developer for further assistance.
Internal session ID: 3c286731-bd67-401f-9fed-a4991821524b
Application Insights session ID: 54f62256-fb76-4ab2-a5b4-a068e891c6ca
Client activity id: 89ba87c8-0dfc-4889-8104-41dca8fd75fe
Time stamp on error: 2025-06-12T08:08:03.6928002Z
User telemetry id: 9e6aed80-8e61-457c-85c6-97fa6b300cd9
AL call stack:
"Report Selections"(Table 77).PrintDocumentsWithCheckDialogCommon line 35 - Base Application by Microsoft version 26.2.34746.34995
"Report Selections"(Table 77).PrintWithDialogForCust line 8 - Base Application by Microsoft version 26.2.34746.34995
"Report Selections"(Table 77).PrintForCust line 8 - Base Application by Microsoft version 26.2.34746.34995
"Serv. Document Print"(CodeUnit 6461).PrintServiceHeader line 22 - Base Application by Microsoft version 26.2.34746.34995
"Service Order"(Page 5900)."&Print - OnAction"(Trigger) line 5 - Base Application by Microsoft version 26.2.34746.34995

**Note:** The error occurs only when work description field is populated. Also, if you go to the service order list page and click print for that same document, the printing is allowed.

**Actual result:** Error "An error occurred, and the transaction is stopped. Contact your administrator or partner for further assistance." when printing a service order with work description from the service order card page.

**Expected result:** The print function should also work from the service order card page if the work description field is populated.

## Description:
Error "An error occurred and the transaction is stopped. Contact your administrator or partner for further assistance." when printing a service order with work description from the service order card page.
