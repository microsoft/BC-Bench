# Title: Copy project: System-Created Entry must be equal to 'No' in Project Planning Line
## Repro Steps:
Create a Project1 for any customer (10000)
Make sure that Apply Usage Link is Enabled (posting tab)
Add new Task1 (Code = 1). No planning lines.

Navigate to project journal and add new line:
Type = Both Budget and Billable. Project1/ Task1 - created earlier. Some document number. Some item with quantity.
Post.

Return to project1, task one. Navigate to project planning lines.
Now there is line. If you use page inspector you can see that System Created Entry = Yes.

Create project2 for same customer.
Choose the "Copy Project Task from" action and select Project1. Remember to activate Copy Quantity toggle in the Apply fasttab.
Select copied Task1 and choose Project Planning Lines.
Select planning line with item and choose "Create Project Journal Line" action. Choose Ok.

Result - Error message:
System-Created Entry must be equal to 'No' in Project Planning Line: Project No.=PR00050, Project Task No.=1, Line No.=10000. Current value is 'Yes'.
AL call stack:
"Job Journal Line"(Table 210)."Job Planning Line No. - OnValidate"(Trigger) line 14 - Base Application by Microsoft
"Job Journal Line"(Table 210)."Quantity - OnValidate"(Trigger) line 18 - Base Application by Microsoft
"Job Journal Line"(Table 210)."Unit of Measure Code - OnValidate"(Trigger) line 47 - Base Application by Microsoft
"Job Transfer Line"(CodeUnit 1004).FromPlanningLineToJnlLine line 60 - Base Application by Microsoft
"Job Planning Lines"(Page 1007)."CreateJobJournalLines - OnAction"(Trigger) line 14 - Base Application by Microsoft

Expected - remove "system-Created Entry" mark when copying project planning lines.

## Description:
