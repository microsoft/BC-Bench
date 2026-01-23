Title: [master] [ALL-E] Error during direct creation of a warehouse receipt and warehouse shipment while using Ampersand (&) in the Location Code.
Repro Steps:
Log into your BC Cronus Environment. Go to the Locations page and enter a New Location Card with a Code containing an ampersand (&) symbol. 3. Create a Warehouse Shipment with the location that has several Special Character above from a Sales order: You will see that you will be able to create the warehouse shipment with no error. 4. Now go to the Location page and create another Location with ampersand (&) in this case S & F 5. Now try to create a Warehouse Shipment with the location that has the ampersand (&) above from a Sales order: We run into this error message. The partner provided few lines of code pointing to what causing the error.
Description:
In conclusion, other special characters work except for ampersand (&). Please look into this. Thanks!
