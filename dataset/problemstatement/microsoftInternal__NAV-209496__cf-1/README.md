# Title: Error message "A reminder attachment text cannot be created without an ID" when adding text for language in Reminder Level Communication

## Repro Steps:
Issue was Reproduced in Version: GB Business Central 25.4 (Platform 25.2.29913.0 + Application 25.4.29661.29959)
**REPRO**
1. Navigate to Reminder Terms, Create a new one
![Reminder Terms Step1](./reminder_terms_step1.png)
2. On the Lines, Navigate to Customer Communication.
![Reminder Terms Setup Step2](./reminder_terms_setup_step2.png)
3. Press No to the next 2 x messages:
![Message Step3](./message_step3.png)
![Message2 Step3](./message2_step3.png)
4. With no Attachment Texts inserted on the communication, press Add text for language.
![Communication Step4](./communication_step4.png) 
5. Say No to the 2x messages,
![Message Step5](./message_step5.png)
![Message2 Step5](./message2_step5.png)
6. Then select the language - GERMAN:
![Languages Step6](./languages_step6.png)

**Actual Result**
Error- A reminder attachment text cannot be created without an ID.
 ![Error](./error.png)

**Expected Result**
The error message should not appear.

## Description:
Error message "A reminder attachment text cannot be created without an ID" when adding text for language in Reminder Level Communication
