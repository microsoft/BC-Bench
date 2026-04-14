# Title: When creating a new price for variant items the variant code should not be preset when the Product No. changes
## Repro Steps:
1. Open BC 22.13 W1
2. Search for "Feature management"
   Activate "New sales pricing experience"
   ![Feature Management](./feature-management.png)
3. Search for Items
   Create a new item
4. Create 3 Variants for this item:
   Actions -> item -> variants
   ![Item Variants](./item-variants.png)
5. Search for "Sales price lists"
   Create a new price list
   Insert a line with your new item (70061) and select a variant "Blue"
   insert a second line for a different item - the variant "Blue" should not be preset when the Product No. changes

ACTUAL RESULT:
the variant "Blue" is automatically presetted even when the Product No. changes
![Sales Price List](./sales-price-list.png)
