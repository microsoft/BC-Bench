Title: [master] [ALL-E] Error on certifying a new version of production BOM if there is another closed version containing BOM loop.
Repro Steps:
Repro Steps: 1. Search and Open Production BOM. 2. Open any Production BOM Number. 3. Click Versions. 4. Open Version 1 and check the status is "Closed". 5. Now create new BOM version 2. 6. Open Version 2 now and make any changes, e.g. update the quantity for an item. 7. Now click "Status". 8. Select Certified and the below error occurs, The Maximum number of Bom Levels, 50 was exceeded. the process stopped at item number, BOM header number 1000, Bom Level 1
Description:

