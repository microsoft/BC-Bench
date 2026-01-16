Title: Approval notifications are not respecting the time zone of the recipient
Repro Steps:
1- Create an Approval Workflow 2- User 1 has: is in GMT Ireland timezone - with Daily schedule of 7am (Irish Time) 3- User 2 is in US Timezone and sends the notification at 14:46 pm US Time 4- Find the notification is sent following day at 11am and not 7am
Description:
[SOLUTION-BEGIN] Issue: When a user in one time zone sends an approval notification to another user who has a schedule setup for example - Daily - the notification is being scheduled according to the user who is sending the notification rather than the user receiving. TEST is in GMT Ireland timezone - with Daily schedule of 7am (Irish Time) TEST1 is in US Timezone and sends the notification at 14:46 pm US Time Notification is sent following day at 11am and not 7am Solution: Bug resolved and PR is backported to 24.x [SOLUTION-END]
