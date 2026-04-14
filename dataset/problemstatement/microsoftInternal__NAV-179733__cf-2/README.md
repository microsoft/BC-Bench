# Title: Copy Project Tasks into Project with Task Billing = Multiple Customers should skip Begin-Total explicitly
## Repro Steps:
Create project1 for any customer (10000)
add task 1 of type Begin-Total and task 2 of type Posting. (no planning lines)
Change Task Billing Method = Multiple Customers.

Choose Copy Project Tasks from...
Select project with Begin/End

Result: Only Begin-Total tasks are explicitly skipped; all other task types inherit customer fields.

Expected: Begin-Total type is explicitly excluded from customer field inheritance.
## Description:
Only Begin-Total tasks should be skipped when copying customer fields in Multiple Customers billing mode.
