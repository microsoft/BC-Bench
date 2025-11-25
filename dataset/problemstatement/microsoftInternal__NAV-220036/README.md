Title: Field Email on Reminder is empty when customer does not have any contacts
Repro Steps:
Tested in latest build 26.x onprem
1.Create a new domestic customer that has no contact, use the template CUSTOMER PERSON
In addition to the automatically added fields, add the following values:
Address: Test
City: Birmingham
Post Code: B27 4KT
Email: test@test.de
Payment Terms Code: 7 Days
Reminder Terms Code: Domestic
2.Then create and post a new Sales Invoice for this customer
Posting Date = 01/01/27
1x item 1896-S
3.Go to the reminders and create a new reminder with button "Create Reminders"
Posting Date = 01/31/27
Document Date = 01/31/27
4.A new reminder should now be created for our new customer. Open that reminder

**Actual Result:**
The field email on the reminder header is empty

**Expected Result:**
The email field should show value test@test.de

**Additional Information:**
Usually the email field on the reminder header does show the email of the contact related to the customer. In our case we do not have a contact, so the email from the customer card should be shown. When you then actually issue and send the reminder, you will notice that BC does take the e-mail adress from the customer card.
But this e-mail adress should also be visible on the reminder page directly.

Description:
Field Email on Reminder is empty when customer does not have any contacts
