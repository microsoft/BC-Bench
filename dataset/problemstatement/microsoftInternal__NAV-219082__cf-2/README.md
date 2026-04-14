# Title: Printing service order should only be allowed from the Service Order List page.
## Repro Steps:
Reported in SE environment.
Happens in W1 as well
Tested in NL 26.2
Open the Company Information and change the User Experience to Premium
1. Go to service order list page
2. Select a service order
3. Click print — works fine from list page
4. Open the service order card page
5. Click print — should not be allowed from here

**Note:** The print function should only be available from the Service Order List page, not from the Card page. When invoked from the Card page context, the print should be blocked.

**Actual result:** The print function is available from both the Card and List pages, but the Card page context causes transaction errors.

**Expected result:** The print function should only work from the service order list page.

## Description:
The print operation should be restricted to the Service Order List page context. The fix should add a page context guard (IsListPageContext) to only allow printing when the operation originates from the list page.
