# Title: Get Posted Purchase Receipt Lines on Transfer Order - Appl-to Item Entry validation
## Repro Steps:
Get Receipt Lines action on Transfer Order populates Appl-to Item Entry but the value is not validated correctly when saved.

![Item Ledger Entries](./item-ledger-entries.png)

The applies to ID is set but not validated correctly due to Modify(false).

## Description:
Appl-to Item Entry set but not validated correctly.
