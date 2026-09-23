# [Master] [all-e][Subscription Billing]Vendor Subscription Price Update Errors - G/L Account Purchase Price Not Updating – Computed Price ≤ 0

## Repro Steps

I have attached a Word Document with the detailed Reproduce Steps. These includes screen shots and exact steps.

See also the attached Video of the partner Teams Meeting for additional clarity.

**SUMMARY OF ISSUE:**
Client has enabled Feature Management: New Sales Pricing Experience.

Client sets up a Vendor Subscription Contract for current year (Jan. 1 - Dec 31, 2026) with a G/L Account (Cleaning Services) identified.

The client sets up a Purchase Price for a G/L Account for the next year (beginning January 1, 2027 - Dec 31. 2027) and want to have the updated Pricing (Direct Cost) for the Vendor managed for the Subscription Billing Vendor Contract.

When running the Subscription Contract Price Update process for a proposal for the new Contract Price on the G/L Account for the Vendor, it errors:

The error message presented shows:

“At least one Price Update line has not been created because the price update would turn the price negative or equal to 0.”


**Expected Outcome:**
The system should successfully create and apply the price update lines for the selected G/L Account without errors. Updated purchase prices should reflect the configured template (fixed amount or percentage) and remain positive values greater than zero. 

**Actual Outcome:**
When attempting to apply the price update for the G/L Account, the system does not create any update lines. Instead, it displays the error message:
“One Price Update line has not been created because the price update would turn the price negative or equal to 0.”

**Troubleshooting Actions Taken:**
Verified Price Update Template Configuration

Checked calculation method (fixed amount vs. percentage/index) to ensure no negative or zero result is produced.

Reviewed Price Source Selection

Confirmed that the correct price list line is being picked for the G/L Account and Vendor scenarios.


Checked Effective Dates and Filters
Validated that the price list entries are active and match required filters (Customer/Vendor, UOM, Currency, Minimum Quantity).

Tested with Simplified Scenario
Created a single price list line with a positive base price and applied a small percentage update to confirm behavior.

Confirmed Product Mapping
Verified that G/L Account exists as a priced product in the relevant price list to avoid fallback to zero base price.

**Did the partner reproduce the issue in a Sandbox without extensions?** Yes
