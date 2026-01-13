Title: [master] When Changing the Unit Amount to 0 in the purchase invoice line, the Non Deductible Vat is not removed.
Repro Steps:
Open Cronus W1. Open Vat Setup and enable Non Deductible Vat. Open Vat Posting Groups. Setup and allow Non Deductible Vat with 10%. Go to Vendors and create a new DOMESTIC vendor. Go to Purchase Invoices and create a new one. Add the Test Vendor. Add the item Athens Desk for example, it will generate Direct Unit Cost Excl Vat and Non Deductible Vat Amount. Change the Direct Unit Cost Excl Vat to 0. After changing it to 0 the Non Deductible Vat Amount is still the same and hasn't been removed. If we do preview posting. The Lines are posted with the Non Deductible Vat Amount.
Description:
When Changing the Unit Amount to 0 in the purchase invoice line, the Non Deductible Vat is not removed.
