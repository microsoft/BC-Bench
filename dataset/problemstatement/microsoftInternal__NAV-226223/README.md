# Title: "Attempted to divide by zero" error during Exchange Rates Adjustment if the company has no Tax/VAT Entries.
## Repro Steps:
Steps to Reproduce:
Used US company, but it is W1
You can use My Company, as it has no VAT/TAX Entries.
1. Go to Currencies and enter a Exch. Rate for EUR with Starting Date.
Also, for EUR, fill the Reporting tab Gains/Losses Accounts fields.
2. In General Ledger Setup, under the Reporting tab, add EUR as Additional Reporting Currency and set “Tax Exchange Rate Adjustment” to "Adjust Additional-Currency Amount"
2. Ensure the company has no VAT entries (VAT Entry table is empty) or you have entries with no tax in the entries you are going to run.
3. Run the Exchange Rates Adjustment process. (Toggle on “Adjust G/L Accounts for Additional Reporting Currency”)
4. The process fails with a divide by zero error. Error message: Attempted to divide by zero.
NOTE: Same happens in NL/W1, selecting USD as Add. Currency for example and No VAT Entries.
**Expected Outcome:**
The system should skip companies or scenarios where no VAT entries exist, rather than failing with a divide by zero error.
**Actual Outcome:**
The process fails with a divide by zero error when no VAT entries are present.
**Troubleshooting Actions Taken:**
Adjust General Ledger Setup:

Navigate to General Ledger Setup.
Locate the option “Adjust G/L Accounts for Addl Reporting Currency”.

If your environment does not use VAT or has no VAT entries, untick this option.

Run the Exchange Rates Adjustment:

After making these changes, rerun the process. The error should no longer occur.

**Did the partner reproduce the issue in a Sandbox without extensions?** Yes

## Description:
"Attempted to divide by zero" error during Exchange Rates Adjustment if the company has no Tax/VAT Entries.
