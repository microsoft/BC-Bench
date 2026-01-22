Title: [master] [ALL-E] An unexpected G/L Entry and VAT amount is posted for a line in purchase invoice with amount 0
Repro Steps:
Open a W1 BC 23.5 database Go to Vat Posting Setup and change VAT % as follows: EU / VAT10 = 10% EU / VAT25 = 20% Create a new purchase invoice for vendor 10000 Vendor Invoice No = 12345678 VAT Bus Posting Group = EU Add two lines: Item = 1896-S VAT Prod Posting Group = VAT10 Quantity = 135 Direct Unit Cost Excl. VAT = 74,85 Item = 1896-S VAT Prod Posting Group = VAT25 Quantity = 30 Direct Unit Cost Excl. VAT = 0 Post the Preview and check the G/L Entries: Actual Result: 7 G/L Entries are created. For the second line with no VAT and no amount we get an unexpected G/L Entry and a VAT Entry with amount 0,01. Expected Result: We should not get G/L Entries for the VAT of the second line. And the VAT entry for the second line should have amount 0.
Description:
An unexpected G/L Entry and VAT amount is posted for a line in purchase invoice with amount 0
