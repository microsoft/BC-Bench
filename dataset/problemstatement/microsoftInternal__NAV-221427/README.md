Title: [master] [ALL-E] The VAT amount wrongly posted when the purchase invoice includes multiple lines with different VAT Prod. Posting Groups.
Repro Steps:
Repro is from an IT database, but issue can be reproduced in W1 as well. 1- Open the VAT posting setup and setup two lines as exact the following especially the names: 2- Open purchase invoice and fill in the fields as exact the following then preview posting and open the VAT entries: The actual result:There is an amount of 0.01 that is appearing on the line of 0 % VATThe expected result:The amount of these lines should be zero.Additional testing:I have changed the name of the VAT Prod. Posting Group, and it's surprisingly solved the issue! Most probably this amount is calculated from the rounding of the second line.
Description:
The VAT amount wrongly posted when the purchase invoice includes multiple lines with different VAT Prod. Posting Groups.
