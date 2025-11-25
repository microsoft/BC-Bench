Title: Report "Exchange Production BOM Item" no longer populates the 'End Date' field of the replaced Item
Repro Steps:
1) go to Production BOM
select 1000

2) Add in Starting Date and Ending Date with Personalize
3) Search for Exchange Production BOM Item
Excnage Item 1100 to Item 70000
Do NOT Create a new Version
**Do not choose Delete Exchanged Component!**
4) Go to Production BOM
open BOM 1000

**Actual Result:**
The replacement item 70000 with Starting date 28-01-2027 is correct
but the replaced item 1100 does not have Ending Date date 28-01-2027

**Expected Outcome:**
The replaced item should have Ending Date 28-01-2027 that signifies it stops being valid automatically

Description:
Report "Exchange Production BOM Item" no longer populates the 'End Date' field of the replaced ItemThis was introduced with BC 25.03.Before this worked as expected.
