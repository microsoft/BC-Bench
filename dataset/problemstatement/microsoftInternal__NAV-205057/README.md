Title: [master] [all-e]Filters Stop Saving in the Create Reminders Setup page in Reminder Automation
Repro Steps:
Tested in GB v.25.2 Microsoft Entra tenant ID: 546c3ce0-2ad6-4d29-9df2-7b4f2cbffcea, Environment: GBSandbox (Sandbox)Session ID (client): 30e3f45e-c16a-4171-91db-852c02d9fa3eSession ID (server): 39476User telemetry ID: 9ca15653-824b-4332-95f8-ca6c369c4e3d REPRO STEPS Search for 'Reminder Automation' and click on the entry of 'Create Reminders' Click on the Setup button in the Scheduling tab: Put in two filters in Customer Filter: Now open Customer filter and remove the second filter then save Actual Result: From this moment, values are no longer saved in the customer filter. same proess applies for Overdue Entries Filter and Apply Fees filters Expected Result:The filters should still be saved.
Description:
Filters Stop Saving in the Create Reminders Setup page in Reminder Automation
