# Title: In the Item Reclassification Journal is the Dimension value wrongly updated by adding a Sales Person to the line
## Repro Steps:
1- Insert dimensions in the East and Main location as following: 
![location card](./location_card.png)
![location east](./location_east.png)
![location main](./location_main.png)
2- Open the item reclassification journals and fill in the fields as following then open the dimensions:
![item reclassification journals](./item_reclassification_journals.png)
![transfer default 10000](./transfer_default_10000.png)
3- Return back to the lines and add a salesperson code that has a dimension:
![item reclassification journals dimension](./item_reclassification_journals_dimension.png)

**Actual Outcome:**
The "new dimension value code" is changed the original dimension value code: HOME
![new dimension value code](./new_dimension_value_code.png)

**Expected Outcome:**
The new dimension value code should keep its value INDUSTRIAL which comes from the new location.

## Description:
The new dimension value appears to be incorrect after the salesperson is inserted.
