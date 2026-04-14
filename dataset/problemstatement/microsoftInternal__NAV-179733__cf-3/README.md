# Title: Copy Project Tasks into Project should apply customer fields regardless of Task Billing Method
## Repro Steps:
Create project1 for any customer (10000)
add task 1 of type Begin-Total and task 2 of type Posting. (no planning lines)

Choose Copy Project Tasks from...
Select any source project.

Result: Customer fields should be applied regardless of whether Task Billing Method is One Customer or Multiple Customers.

Expected: The Task Billing Method setting should not affect whether customer fields are inherited during copy.
## Description:
Task Billing Method should not gate customer field inheritance when copying project tasks.
