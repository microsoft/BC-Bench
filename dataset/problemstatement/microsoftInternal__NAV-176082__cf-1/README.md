# Title: Get Posted Purchase Receipt Lines on Transfer Order - location filtering
## Repro Steps:
Get Receipt Lines action on Transfer Order shows only receipts with matching header location, not line-level location.

![Posted Purchase Receipts](./posted-purchase-receipts.png)

Only receipts where the header Location Code matches Transfer-from Code are shown.

## Description:
Only receipts with matching header location are shown in Get Receipt Lines.
