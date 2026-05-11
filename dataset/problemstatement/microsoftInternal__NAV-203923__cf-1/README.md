# Title: Full VAT is not treated as eligible for non-deductible VAT calculation
## Repro Steps:
*** Were you able to reproduce the issue? Yes

The situation cx is testing is for a prospect who wants to post all their tax as non-recoverable and then make a quarter end adjustment for the recoverable VAT.

At the end of the quarter, I want to post a journal with a FULL NORM type VAT for the recoverable portion of the VAT and a FULL NORM 100% Non-deductible to move the VAT from Non-Deductible VAT Amount to Amount.

Full VAT is not treated as eligible for non-deductible VAT calculation. When you make the change in the VAT posting setup to Full VAT in the Calculation Type, the system does not recognize it as a valid type for non-deductible processing.

![VAT Posting Setup](./vat-posting-setup.png)

![Journal for VAT Adjustment](./journal-for-vat-adjustment.png)

![VAT Posting](./vat-posting.png)

## Description:
Full VAT is not treated as eligible for non-deductible VAT calculation
