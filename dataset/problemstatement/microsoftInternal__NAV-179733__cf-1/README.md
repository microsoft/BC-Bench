# Title: Copy Project Tasks into Project with Task Billing = Multiple Customers should inherit customer for all task types
## Repro Steps:
Create project1 for any customer (10000)
add task 1 of type Begin-Total and task 2 of type Posting. (no planning lines)
Change Task Billing Method = Multiple Customers.

Choose Copy Project Tasks from...
Select project with Begin/End

Result: Begin-Total tasks should also inherit Customer fields from the target project.

Expected: All task types including Begin-Total should inherit Sell-to and Bill-to Customer from the project.
## Description:
Begin-Total task type should also inherit customer fields when copying into Multiple Customers project.
