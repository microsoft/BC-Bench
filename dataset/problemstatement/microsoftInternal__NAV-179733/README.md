# Title: [Preview] Project Task Type must be equal to 'Posting' in Project Task: Project No.=J00080, Project Task No.=100. Current value is 'Begin-Total'.. when Copy Project Tasks into Project with Task Billing = Multiple Customers
## Repro Steps:
Create project1 for any customer (10000)
add task 1 of type posting. (no planning lines)
Change Task Billing Method = Multiple Customers.

Choose Copy Project Tasks from...
Select project with Begin/End
Result. Error:
    Project Task Type must be equal to 'Posting' in Project Task: Project No.=J00080, Project Task No.=100. Current value is 'Begin-Total'.
## Description:
Not a ship stopper. we will need backport to 24x. please consider hotfix for 24.0 as well (once released)
