# Subcontracting: Create Transfer Order shows only last transfer order when multiple are created

## Repro Steps

### Prerequisites

1. Have an item set up for subcontracting production (routing line marked as WIP Item, subcontractor location code 82000)
2. No BOM needed for this repro

### Steps

1. Create several Production Orders for the same item but with **different Location Codes** (e.g., BLUE, RED, GREEN)
2. Open the **Subcontracting Worksheet**
3. Run **Calculate Subcontracts** to populate the worksheet
4. Run **Carry Out Action Message** — system creates one Purchase Order with multiple lines (one per production order), each line having a different Location Code
5. Open the created Purchase Order
6. Run **Create Transf. Ord. to Subcontractor** action

### Expected Result

System creates multiple transfer orders (one per distinct location combination) and opens the **Transfer Orders list page** showing all created transfer orders.

### Actual Result

System creates multiple transfer orders correctly, but only opens and shows **one** of them (the one linked to the last purchase line processed). The user has no visibility into the other created transfer orders.

### Technical Details

File: `SubcCreateTransfOrder.Report.al`

## Description

When using **Create Transf. Ord. to Subcontractor** action on a Purchase Order created from the Subcontracting Worksheet, if the purchase order has lines with different Location Codes (resulting in multiple transfer orders being created), the system only opens/shows the last created transfer order instead of showing a list of all created transfer orders.

###
