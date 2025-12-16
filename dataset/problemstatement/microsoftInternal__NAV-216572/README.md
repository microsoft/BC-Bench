# Title: In Recurring General Journals Import from Allocation Accounts does not import dimensions
## Repro Steps:
Repro steps in US version to use Allocation Accounts in Recurring General Journals: 
Create an allocation account, assign dimensions on each line.
![Allocation Account Test](./allocation_account_test.png)
Each line has its dimension:
![Alloc Account Distribution Test 10000](./alloc_account_distribution_test_10000.png)
In Recurring General Journals, create a journal line. Navigate to Home/Process > Allocations.
![Recurring General Journals](./Recurring_General_Journals.png)
Choose "Import from Allocation Account"
![Import From Allocation Account](./import_from_allocation_account.png)
Choose the Allocation Account you chose earlier:
![Allocation Accounts](./allocation_accounts.png)
Both lines from AA come. Open the dimensions for each line:
![Allocation Dimensions](./allocation_dimensions.png)
Dimensions come empty:
![Recurring Default 10000](./recurring_default_10000.png)

Expected Result:
The lines should have the same dimesion as setup on the Allocation Account.

## Description:
In Recurring General Journals Import from Allocation Accounts does not import dimensions.
When you use the Allocation Account on a General Journal line, the dimensions are added correctly.
