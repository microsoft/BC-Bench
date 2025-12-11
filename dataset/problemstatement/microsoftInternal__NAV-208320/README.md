# Title: The Email and Phone No. don't update when selecting Another Customer in the "Bill-to" field of a Sales Invoice
## Repro Steps:
1. Go to Contacts and find CT000012 - "Miss Patricia Doyle" with 'Company Name' = (John Haddock Insurance Co.)
2. Edit the contact and add any 'Phone Number' and 'Mobile Phone No.'
3. Go to Sales Invoices and Create a new sales invoice and for Customer 10000.
3. Go down to the Shipping and Billing tab and set 'Bill-to' = "Another Customer"
  Now see how more fields are introduced, including the Contact and Contact info with Phone numbers and email, should be for "Mr. Andy Teal" who is contact for Customer 10000.
5. Then set Name = 30000 (John Haddock Insurance Co.) and say yes to change bill-to customer.
Notice we have Contact = "Miss Patricia Doyle"....

**EXPECTED RESULTS:** The Phone Number(s) and Email for "Miss Patricia Doyle" should pull in.
**ACTUAL RESULTS:** The fields are the same as they were for the previous contact "Mr. Andy Teal" and you need to refresh the Page so it pulls in the new Phone numbers and email for "Mr. Andy Teal" Contact.
## Description:
Copied and Derived from Support Case Review
