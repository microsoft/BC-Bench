# Title: New AR rolecenter: the system should fallback to WorkDate only when Today is not initialized
## Repro Steps:
Note: the system should fallback to WorkDate only when Today is not initialized (returns 0D)

besically you can ignore the repro and just implement the correct filter date

repro: the total Overdue (LCY) cue is using wrong date:
open the new AR rolecenter
go to My settings: update workdate - use today's date
expected: the cue should use Today() when available, and fallback to WorkDate() only when Today() = 0D

actual: cue always uses WorkDate() regardless of whether Today() is available
![Customer Ledger Entries Current](./customer-ledger-entries-current.png)

expected value:
![Customer Ledger Entries Expected](./customer-ledger-entries-expected.png)

## Description:

## Hints

Also, found that calculation and drilldown for "Total Overdue (LCY)" are not in line.
