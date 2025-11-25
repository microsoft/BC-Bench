Title: Your Reference Field Not updated in Customer Ledger Entries, when changed with Update document on posted Sales Invoice
Repro Steps:
1.On a Cronus environment, pick any a posted sales invoice and click on update document
2.On the UPDATE DOCUMENT PAGE change YOUR RERENCE to TEST 1 and click Ok
Upon inspecting the page, the field you "Your reference" is correctly updated in the document
3Add the 'YOUR REFERENCE' field to the lines via Personalize, then use 'Find Entries' to review the customer ledger entries. You'll notice that even after updating 'YOUR REFERENCE' to "TEST 1," the Customer ledger entry still shows the previous reference value unchanged.

**Expected Outcome:**
"YOUR REFERENCE" field is expected to update the Customer ledger entry accordingly when changes are made.

**Actual Outcome:**
the ledger still shows the previous reference value unchanged.

**Troubleshooting Actions Taken:**
In the meantime, the only two viable workarounds I've identified are:
1.Posting a credit memo and reissuing the invoice
2.Utilizing a developer license and a configuration package to populate the Your Reference field

Description:
When editing the 'your reference' field before posting a sales invoice, the value correctly pulls through to the customer ledger entries. However, if the sales invoice is posted first and then the 'your reference' field is entered by update document, it does not pull through to the customer ledger entries
