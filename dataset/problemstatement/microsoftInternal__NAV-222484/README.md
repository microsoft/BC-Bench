# Title: Escalated Error: Lot No. LOT0001 is not available on inventory or it has already been reserved for another document. when trying to register pick for item with reservation and item tracking with location set up FEFO
## Repro Steps:
1- Item Tracking Code:
![Item Tracking Code Card](./item_tracking_code_card.png)
2- Item Card:
![Item Card](./item_card.png)
3- Location Card:
![Location Card](./location_card.png)

**The repro steps:**
1- Open Item Journals and fill in the fields as following then click on Item tracking lines and assign LOT manually and expiration date as following:
![Item Journals Item Tracking Lines](./Item_Journals_item_tracking_lines.png)
![Items Tracking Lines 1001 Lotrepro](./items_tracking_lines_1001_lotrepro.png)
2- Replicate the first step but with changing the Posting Date, LOT No. and Expiration Date Then post the Item Journals:
![Posting Date](./posting_date.png)
![Expiration Date](./expiration_date.png)
3- Create a new sales order and fill in the fields as following then click on Line > Functions > Reserve > Reserve from Current Line:
![Sales Order 101021 Adatum](./sales_order_101021_adatum.png)
![Reservation Order 101021 1001](./reservation_order_101021_1001.png)
4- Replicate step 3 with a new sales order:
![New Sales Order 101021](./new_sales_order_101021.png)
![New Reservation Order 101021](./new_reservation_order_101021.png)
5- Create a warehouse shipment from the second sales order and then create a pick:
![Warehouse Shipment Sh000007](./warehouse_shipment_sh000007.png)
6- Open the pick lines and click on 'Register Pick':
![Warehouse Pick](./warehouse_pick.png)

**The actual result:**
Error will be appearing:
![Error](./error.png)

**The expected result:**
It should be registered successfully without any errors.

## Description:
Error: Lot No. LOT0001 is not available on inventory or it has already been reserved for another document. when trying to register pick for item with reservation and item tracking with location set up FEFO
