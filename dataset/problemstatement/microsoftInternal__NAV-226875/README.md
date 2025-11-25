Title: Payables Journal Lines entered will populate the Vendor Name column with the Description of the G/L Account and not just the Description column
Repro Steps:
Search for Purchase Journals - Make sure Vendor Name column is shown through Personalization.
Enter Today's Date as the Posting Date
Select Account Type of G/L Account and select Account Number (64100 - Office Supplies)
Result: The Description is populated with the Account Name as shown and is expected. However, the column labelled Vendor Name is populated with the Account No, Description, too, which is unexpected.

If the user enters through the line and selects the Bal. Account Type Vendor and Enters a Bal. Account No. of 10000, the Vendor Name column still doesn't show the Vendor Name validated.

**Expected Outcome:**
Validation of the G/L Account No. doesn't fill in the Vendor Name with the same value as the Description name.

**Actual Outcome:**
When a User selects an Account Type of GL Account, it puts the G/L Account Name into the Description field AND the Vendor Name column.
Description:
