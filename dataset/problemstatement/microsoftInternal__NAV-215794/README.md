Title: Wrong entries are applied to Bank Deposit lines when there are multiple lines for the same customer and Lump Sum is enabled
Repro Steps:
**Actions:**
Make sure you have app Bank Deposits ("id": "7a129d06-5fd6-4fb6-b82b-0bf539c779d0") installed.
Open Bank Deposits page, create a new deposit.
Set Bank Account No., enable "Post as Lump Sum" option.
Create a new line for Customer or Vendor, let's say it is for Customer 30000.
Press Functions - Apply Entries. On the page Apply Customer Entries select first two lines, press Set Applies-to ID, press OK.
Create one more line for the same Customer 30000, apply the next two invoices in the list.
Create the third line for the same Customer 30000, apply the next two invoices in the list.
*   Check the amounts in Amount and Credit Amount fields.
*   Run the report Posting - Test Report with enabled option Show Applications.

**Expected result:**
Credit Amount and Amount fields contains the sum of amounts of entries that were applied to them, i.e. first line has sum of amounts of the first 2 invoices, second line has sum of amonts of the next two invoices etc.
Test report shows 2 invoices applied to each bank deposit line. Amounts are the same as we have in the Bank Deposit card.

**Actual result:**
Credit Amount and Amount fields are not correct for the second and the third lines. The second line has amount of the first 4 invoices, the third line has amount of the first 6 invoices, i.e. the amount of each next line contains the amount of the previous line + the amount of newly applied invoices.
Test report shows mess, see the attachment.

Description:

