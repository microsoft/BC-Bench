# Title: In Recurring General Journals Import from Allocation Accounts does not import dimensions
## Repro Steps:
Repro steps in US version to use Allocation Accounts in Recurring General Journals:
Create an allocation account with a single distribution line, assign dimensions on the line.
![Allocation Account Test](./allocation_account_test.png)
The line has its dimension:
![Alloc Account Distribution Test 10000](./alloc_account_distribution_test_10000.png)
In Recurring General Journals, create a journal line. Navigate to Home/Process > Allocations.
![Recurring General Journals](./Recurring_General_Journals.png)
Choose "Import from Allocation Account"
![Import From Allocation Account](./import_from_allocation_account.png)
Choose the Allocation Account you chose earlier:
![Allocation Accounts](./allocation_accounts.png)
The line from AA comes. Open the dimensions:
![Allocation Dimensions](./allocation_dimensions.png)
Dimensions come empty:
![Recurring Default 10000](./recurring_default_10000.png)

Expected Result:
The lines should have the same dimesion as setup on the Allocation Account when multiple allocation distribution lines exist.

## Description:
In Recurring General Journals Import from Allocation Accounts does not import dimensions.
When you use the Allocation Account on a General Journal line, the dimensions are added correctly.
