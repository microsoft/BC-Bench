Title: If you create a pick with several lines with diffrenct Lot No. Expiration date and a location with Pick According to FEFO = Yes picking from different BINS lead to a rounding issue.
Repro Steps:
1. Open BC26.1 W1
2. Open Warehouse Employees
    Add your user for location SILVER
3. Open Location SILVER
    Require Pick: YES
    Pick According to FEFO = Yes
4. Create a new Item (70072 Rounding Test)
    Base UOM = PCS
    Item Tracking: LOTALLEXP
    ![item](./item.png)
5. Add a second UOM to the Item
    Item Card -> Related -> Item -> Units of Measure
    Select PACK -> Qty. per Unit of MEasure = 2,888
    Quantity Rounding Precision = 0,00001

    Back in the Item Card
    Change Sales Unit of Measure to PACK
6. Open the Item Journal
    Open the DEFAULT Batch -> 3 Dots
    Item Tracking Lines = yes
7. Use the Personalization to move or add the fields as in the scrrenprint below:
    ![item journals](./item_journals.png)
    You can try to copy and paste the following lines:

    | Posting Date | Entry Type | Document No. | Item No. | Description | Location Code | Bin Code | Quantity | Lot No. | Expiration Date | Unit of Measure Code | Unit Amount | Amount | Discount Amount | Unit Cost | Applies-to Entry | Serial No. | Warranty Date | Department Code | Project Code | Customergroup Code | Area Code | Businessgroup Code | Salescampaign Code |
    |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0001 | 434,97616 | LOT01 | 30.11.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0001 | 17,3126 | LOT03 | 25.09.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0001 | 17,0373 | LOT06 | 25.09.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0002 | 4,13394 | LOT01 | 25.09.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0002 | 4,34355 | LOT02 | 30.11.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0002 | 151,33333 | LOT03 | 25.09.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0002 | 40,01221 | LOT04 | 06.06.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0003 | 1,78787 | LOT02 | 16.05.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0003 | 42,73313 | LOT03 | 25.09.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |
    | 28.01.2027 | Positive Adjmt. | T00009 | 70072 | Rounding Test | SILVER | S-03-0003 | 4,013 | LOT05 | 13.07.2025 | PCS | 0,00 | 0,00 | 0,00 | 0,00 | 0 |  |  |  |  |  |  |  |  |

    Post
8. Create a new Sales Order
    Customer:10000
    Item 70072
    Location: SILVER
    Quantity: 248
    UOM: PACK
9. Create an Inventory Pick
    Home > Create Inventory Put-away/Pick > select Create Invt. Pick
10. Open the created Pick
    Related > Warehouse > Invt. Put-away/Pick Lines
    Show Document
    Add by personalization the field Qty. to Handle (Base)
    The following lines are created

    | Item No. | Description | Bin Code | Lot No. | Qty. per Unit of Measure | Quantity | Qty. to Handle | Qty. to Handle (Base) | Qty. Handled | Qty. Outstanding | Unit of Measure Code |
    |---|---|---|---|---|---|---|---|---|---|---|
    | 70072 | Rounding Test | S-03-0002 | LOT04 | 2,888 | 13,85464 | 13,85464 | 40,01221 | 0 | 13,85464 | PACK |
    | 70072 | Rounding Test | S-03-0003 | LOT05 | 2,888 | 1,38954 | 1,38954 | 4,013 | 0 | 1,38954 | PACK |
    | 70072 | Rounding Test | S-03-0001 | LOT03 | 2,888 | 5,99467 | 5,99467 | 17,3126 | 0 | 5,99467 | PACK |
    | 70072 | Rounding Test | S-03-0002 | LOT03 | 2,888 | 52,40074 | 52,40074 | 151,33333 | 0 | 52,40074 | PACK |
    | 70072 | Rounding Test | S-03-0003 | LOT03 | 2,888 | 14,79679 | 14,79679 | 42,73313 | 0 | 14,79679 | PACK |
    | 70072 | Rounding Test | S-03-0001 | LOT06 | 2,888 | 5,89934 | 5,89934 | 17,0373 | 0 | 5,89934 | PACK |
    | 70072 | Rounding Test | S-03-0001 | LOT01 | 2,888 | 150,61501 | 150,61501 | 434,97616 | 0 | 150,61501 | PACK |
    | 70072 | Rounding Test | S-03-0002 | LOT01 | 2,888 | 1,43142 | 1,43142 | 4,13394 | 0 | 1,43142 | PACK |
    | 70072 | Rounding Test | S-03-0002 | LOT02 | 2,888 | 1,504 | 1,504 | 4,34355 | 0 | 1,504 | PACK |
    | 70072 | Rounding Test | S-03-0003 | LOT02 | 2,888 | 0,11384 | 0,11384 | 0,32878 | 0 | 0,11384 | PACK |

    If you sum up the Quantity it is 247,99999 and not 248
11. Autofill Qty. to Handle
    Post the pick -> just ship
12. Go back to the sales order

ACTUAL RESULT:
Not the full quantity has been picked
![lines](./lines.png)

If you try to create a second pick
Nothing to pick
0,00001 PACK * 2,888 = 0,00003 Pcs

EXPECTED RESULT:
The piick should have picked the full quantity.

ADDITIONAL INFORMATION:
The posted pick lines

| Item No. | Description | Bin Code | Lot No. | Quantity | Qty. (Base) | Due Date | Unit of Measure Code |
|---|---|---|---|---|---|---|---|
| 70072 | Rounding Test | S-03-0002 | LOT04 | 13,85464 | 40,0122 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0003 | LOT05 | 1,38954 | 4,01299 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0001 | LOT03 | 5,99467 | 17,31261 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0002 | LOT03 | 52,40074 | 151,33334 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0003 | LOT03 | 14,79679 | 42,73313 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0001 | LOT06 | 5,89934 | 17,03729 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0001 | LOT01 | 150,61501 | 434,97615 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0002 | LOT01 | 1,43142 | 4,13394 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0002 | LOT02 | 1,504 | 4,34355 | 28.01.2027 | PACK |
| 70072 | Rounding Test | S-03-0003 | LOT02 | 0,11384 | 0,32877 | 28.01.2027 | PACK |

If you compare the posted pick lines and the pick lines many entries differ int the Qty. Base.
I was just able to create the rouding issue with the different Expiration Dates and the Pick According to FEFO I assume the order might be of importance.

Description:
If you create a pick with several lines with diffrenct Lot No. Expiration date and a location with Pick According to FEFO = Yes picking from different BINS lead to a rounding issue.
