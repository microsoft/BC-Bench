# Title: Wrong Decimal Rounding with Quantity in Reservation Entries, using Order Tracking Policy where tracking lines are split into 3, each ending in x.xxxx7, which results with all 3 adding up to x.00001
## Repro Steps:
1. Create new item 1000 or whatever number.
2. On the Item in Related > Item > Units of Measure, Add UOM for CASE (CA), Qty 24 Per Base UOM of PCS
3. **Set 'Sales UOM' = CASE**
4. Set 'Order Tracking Policy' = Tracking & Action Messages
5. Set Item Tracking to LOTALL
6. Create Item Journal for Positive Adj., 12 CASES (or 288pcs), MAIN Location and go into Item tracking and set LOT to LOTDECIMAL01 with 288 Quanty and then Post
7. Now create another Item Journal for Positive Adj., 440 PCS, MAIN Location and go into Item tracking and set LOT to LOTDECIMAL02 for 220 Quantity and then add a 2nd line for 220 Quantity of LOTDECIMAL03.
8. Post.
9. Create a new Sales Order for Customer 50000, for the item at MAIN Location for 12 CASES.
10. Review Table 339 and you can see the 12 cases (288 pcs Qty) are split into 2 and Tracking against the last 2 LOTs posted.
11. Then on the Sales Order, go into Lines > Item Tracking Lines and choose the first lot you posted, LOTDECIMAL01 for 288 quantity.
12. Review Table 339 and you can see the 12 cases (288 pcs Qty) are still split into 2 and Tracking against the LOTDECIMAL01. All good so far.
13. Now in the Item Tracking Lines, change the 'Quantity (Base)' from 288 to 13 and go out of Item Tracking Lines.
14. Review Table 339 and you can see we have our Sales Order now split out into 3 Tracking Lines.

**EXPECTED RESULTS:**Summed Quantity is 12
**ACTUAL RESULTS:** If we add the 'Quantity' together, we get 12.00001

## Description:
Copied and derived from Support Case Review
