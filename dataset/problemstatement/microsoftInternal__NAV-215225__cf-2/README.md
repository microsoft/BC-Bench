# Title: Recurring Project Journal is not handy to use as the posted lines needs to be revalidated to get again the Unit Amounts for the next posting.
## Repro Steps:
1- Navigate to the Recurring Project Journal.
2- Add a new line with the following details and post it:
Recurring Method | Recurring Frequency | Line Type | Posting Date | Document No. | Project No. | Project Task No. | Type     | No.       | Description    | Location Code | Work Type Code | Unit of Measure Code | Quantity | Unit Cost | Unit Cost (LCY) | Total Cost | Total Cost (LCY) | Unit Price | Line Amount | Line Discount % | Line Discount Amount | Applies-to Entry | Expiration Date
Variable         | 1M                  | Billable  | 4/30/2025    | TEST2        | JOB00010    | 1010             | Resource | KATHERINE | KATHERINE HULL |               |                | HOUR                 | 1        | 55.00     | 55.00           | 55.00      | 55.00            | 100.00     | 100.00      | 0.00            | 0.00                 | 0                |

3- After posting, all the lines will appear as zeroes:
Recurring Method | Recurring Frequency | Line Type | Posting Date | Document No. | Project No. | Project Task No. | Type     | No.       | Description    | Location Code | Work Type Code | Unit of Measure Code | Quantity | Unit Cost | Unit Cost (LCY) | Total Cost | Total Cost (LCY) | Unit Price | Line Amount | Line Discount % | Line Discount Amount | Applies-to Entry | Expiration Date
Variable         | 1M                  | Billable  | 4/30/2025    | TEST2        | JOB00010    | 1010             | Resource | KATHERINE | KATHERINE HULL |               |                | HOUR                 | 0        | 0.00      | 0.00            | 0.00       | 0.00             | 0.00       | 0.00        | 0.00            | 0.00                 | 0                |

4- If you add the quantity in the lines, the unit cost will not be updated:
Recurring Method | Recurring Frequency | Line Type | Posting Date | Document No. | Project No. | Project Task No. | Type     | No.       | Description    | Location Code | Work Type Code | Unit of Measure Code | Quantity | Unit Cost | Unit Cost (LCY) | Total Cost | Total Cost (LCY) | Unit Price | Line Amount | Line Discount % | Line Discount Amount | Applies-to Entry | Expiration Date
Variable         | 1M                  | Billable  | 4/30/2025    | TEST2        | JOB00010    | 1010             | Resource | KATHERINE | KATHERINE HULL |               |                | HOUR                 | 2        | 0.00      | 0.00            | 0.00       | 0.00             | 0.00       | 0.00        | 0.00            | 0.00                 | 0                |
**Expected Outcome:**
The Unit Price and Unit Cost should only be restored after posting when the Quantity on the journal line is greater than zero. If Quantity is 0, the values should remain zero after posting.
## Description:
Recurring Project Journal should only restore Unit Cost and Unit Price when Quantity > 0.
