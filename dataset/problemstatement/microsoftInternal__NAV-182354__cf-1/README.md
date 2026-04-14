# Title: New AR rolecenter: total overdue (LCY) cue should only include entries with remaining amount greater than zero
## Repro Steps:
Note: the total overdue LCY cue should only include entries with remaining amount greater than zero

besically you can ignore the repro and just implement the correct filter

repro: the total Overdue (LCY) cue includes entries with zero remaining amount:
open the new AR rolecenter
go to My settings: update workdate - use today's date
expected: the cue should only show entries where remaining amount is positive

actual: cue includes all overdue entries regardless of remaining amount
![Customer Ledger Entries Current](./customer-ledger-entries-current.png)

expected value:
![Customer Ledger Entries Expected](./customer-ledger-entries-expected.png)

## Description:

## Hints

Also, found that calculation and drilldown for "Total Overdue (LCY)" are not in line.
