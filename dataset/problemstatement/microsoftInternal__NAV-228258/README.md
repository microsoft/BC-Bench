Title: Issue with the new feature for reminder texts where the configured body text is not included in the XML for report 117 (Reminder)
Repro Steps:
1) Set a Customer Card as below.
![customer card](./customer_card.png)
2) Create a Sales Invoice for that customer, with the dates as shown below; and post the Invoice.
![sales invoice](./sales_invoice.png)
3) Make sure the reminder feature is enabled.
![feature management](./feature_management.png)
4) In Reminder Terms, select the same one setup for the customer.
5) Click on Customer Communication for each Level to edit the default message.
![reminder terms setup](./reminder_terms_setup.png)
6) Click “Add text for language”, then add “NLD”; and select it from “Language Code”.
7) Edit the message body.
![reminder level communication](./reminder_level_communication.png)
8) Go into Reminders and create a new one for the same customer.
9) Select the date, then click “Suggest Reminder Lines”.
![reminder](./reminder.png)
10) Issue the reminder.
11) Go into Issued reminders > Select the created reminder > Send by Email.
![issued reminders](./issued_reminders.png)
12) The customized message will show up.
![email edit](./email_edit.png)
13) In Issued Reminders > Select Print.
![issue reminders print](./issued_reminders_print.png)
14) 14) Send To.
![reminder request page](./reminder_request_page.png)
15) Select XML Document.
![reminder request file type](./reminder_request_file_type.png)
16) At the bottom of the document, "AmtDueText" is blank.
![AmtDueText xml blank](./AmtDueText_xml_blank.png)
17) If we change the Language code in the Customer Card for FRA for example, without creating a customized text for that language, it will show as below.
![customer card language code](./customer_card_language_code.png)
![AmtDueText xml value](./AmtDueText_xml_value.png)
18) Same happens for Netherlands, if change the Language Code back to NLD.
19) Then delete the customized text from the Reminder Terms for all the levels.
![reminder level communication remove](./reminder_level_communication_remove.png)
20) Issued reminders will now show the BodyText in AmtDueText.
![AmtDueText xml value NLD](./AmtDueText_xml_value_NLD.png)
![issued reminders NLD](./issued_reminders_NLD.png)
* The customer says he expects the issue to be with this part of the code.
![code](./code.png)

**Expected Outcome:**
The customer expects the customized message body to be included in the XML report in the “AmtDueText” section.

**Actual Outcome:**
There is no message included in the XML report in the “AmtDueText” section.

**Troubleshooting Actions Taken:**
Tried the same flow with different languages.Did the partner reproduce the issue in a Sandbox without extensions? Yes

Description:
