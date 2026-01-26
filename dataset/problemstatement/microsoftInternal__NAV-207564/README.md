# Title: Issue with Non-Deductible VAT rounding when using Reverse Charge VAT
## Repro Steps:
**The setup:**
1- Currency Card
![Currency Card](./currency.png)

2- Currency exchange rate:
![Currency Exchange Rate](./currency-exchange-rate.png)

3- Vat Posting Setup:
![VAT Posting Setup](./vat-posting-setup.png)
4- General Ledger Setup:
![General Ledger Setup](./general-ledger-setup.png)

**The repro steps:**
1- Create purchase invoice and set fields as following then click on preview posting:
![Purchase Invouce](./purchase-invoice.png)

![Purchase Invoice Preview Posting](./purchase-invoice-preview-posting.png)

**The actual result:**

The non-deductible VAT is rounded to 25 based on the Rounding Precision set up in the Currency Card, rather than the Rounding Precision configured in the General Ledger Setup.
![G/L Entries Preview](./gl-entries-preview.png)

**The expected result:**

The value should be rounded to 24.81 according to the Rounding Precision set up in the General Ledger Setup, rather than the Rounding Precision configured on the currency card.

​I have tried to replicate the scenario using the normal VAT instead of Reverse Charge VAT and it worked as expected.
![G/L Entries Preview Expected](./gl-entries-preview-expected.png)

## Description:
Issue with Non-Deductible VAT rounding when using Reverse Charge VAT
