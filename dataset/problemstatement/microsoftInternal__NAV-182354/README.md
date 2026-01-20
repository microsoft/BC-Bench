# Title: New AR rolecenter: total overdue (LCY) cue is using wrong date
## Repro Steps:
Note: we must use today() as the filter date for this cue
work date is intended for data entry, not for filtering the UI in rolecenters per default

besically you can ignore the repro and just implement the correct filter date

repro: the total Overdue (LCY) cue is not updated correctly when you update work date:
open the new AR rolecenter
go to My settings: update workdate - use today's date
expected: the cue should have updated value (maybe after some time; not sure if this is bckgrnd process)

actual: cue is never updated even if the filer is correctly set, e.g. open the cue and check the entries:
![Customer Ledger Entries Current](./customer-ledger-entries-current.png)

expected value:
![Customer Ledger Entries Expected](./customer-ledger-entries-expected.png)

## Description:
