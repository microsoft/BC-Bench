# Title: In the Sales Price Lists, the 'Defines' field always defaults to Price & Discount when dealing with Customer Price Group/Customer Disc Group setting
## Repro Steps:
Reproduced in CRONUS GB v25.4
Enable 'New Sales Price Experience' in Feature Management.
1. Go to Sales Price Lists
2. Click on New to generate a New Sales Price List.
3. Set Assign-to-type to Customer Disc. Group
4. View Columns for: **Discount**
5. Insert a single item line, using only Line Discount.
6. Set the Sales Price List to Status 'Active'
7. Go back to the Sales Price Lists Page.

You will notice "Defines" has changed back to Prices & Discounts Same behavior is replicable with Price for Customer Price Group
**Expected Result:** Defines should remain as Discounts if only discounts are in the Sales Price list
**Actual Results:** 'Defines' Always defaults to 'Prices & Discount'

## Description:
The issue is with the setting for the "Defines" field. The setting may be changed from 'Price & Discount' to 'Discount' because only Line Discounts may be used in the new Price Group configuration. However, after closing the Page, the system will always default back to the 'Price & Discount', even though only Line Discounts are defined, because the code doesn't pass the value correctly.

The Partner Developer highlighted the following code:
The call stack:
- GetAmountType (\ext11_packandshipchanges\Table\7005\Price Source.dal:342)
- GetDefaultAmountType (\ext11_packandshipchanges\Table\7005\Price Source.dal:182)
- UpdateAmountType (\ext11_packandshipchanges\Table\7000\Price List Header.dal:567)
- OnClosePage (\ext11_packandshipchanges\Page\7016\Sales Price List.dal:600)

In the Function:`UpdateAmountType`, the following code is used:
"Amount Type" := PriceSource.GetDefaultAmountType(); The code reflects it as empty. No value is passed to it, so it always defaults to 'Price & Discount'
