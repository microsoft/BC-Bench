Title: Contact xxx is not related to a customer error when using Change Customer in a Service Contract
Repro Steps:
1. Create a New Contact Card with Type Person. (No. = CT000028)
2. Actions - > Functions - > Create As - Customer.
3. Now It will appear in the Business Relation.
4. Go to Service Contracts and create new one for Customer 10000 Adatum.
5. Click Change Customer.
6. Now choose your customer (created in step 2).
7. The following error occurs. "Contact CT000028 Change Contact is not related to a customer."
8. Contact xxx is not related to a customer.

**Expected Results:**
* The Contact has a Business Relation as it was created with a Customer, It should be changed successfully with no issues.

**Investigation:**
* On "Service Contract" page, If you change the Customer from the "Customer No." Field, It works with no errors.
Description:
