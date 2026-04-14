# Title: Error when printing a service order with work description — transaction commit should not depend on GUI mode.
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

**Note:** The error occurs because the transaction commit is conditionally gated on GUI mode. Whether or not the session is in GUI mode, the commit should always be performed before running the report modal.

**Actual result:** Error "An error occurred, and the transaction is stopped. Contact your administrator or partner for further assistance." when printing a service order with work description from the service order card page.

**Expected result:** The print function should work only after the transaction is committed regardless of GUI mode.

## Description:
Error "An error occurred and the transaction is stopped. Contact your administrator or partner for further assistance." when printing a service order with work description. The fix should ensure Commit() is always called before REPORT.RunModal, not only when IsGUI is true.
