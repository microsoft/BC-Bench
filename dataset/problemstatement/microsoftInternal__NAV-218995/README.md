# Title: Error when posting a Purchase Credit Memo for 'Non-Inventory' item with Project No. selected
## Repro Steps:
Issue Description:
When trying to post a purchase credit memo for project with non-inventory item, encounter this error message. "You must post more usage or credit the sale of Item 0001035467 in Project 536188 before you can post purchase credit memo ZPC1000070 Line No. = 10000."
![Error Message](./error_message.png)

Investigation:
Reproduce the same problem in clean US environment
Here are the reproduce steps:
1.Navigate to the Items page > Create a non-inventory item (item with non-inventory type).
![Item Card 1001](./item_card_1001.png)
2.Create a project card
![Project Card](./project_card.png)
3.Create new purchase credit memo having that item and link it to a project number, fill in the project task no and project line type as well.
![Purchase Credit Memo 2](./purchase_credit_memo_2.png)
4.Post the memo -> Error message: You must post more usage or credit the sale of Item 1001 in Project PR00030 before you can post purchase credit memo 1008 Line No. = 10000.
![Error Message Step4](./error_message_step4.png)
Other details: Customer said this is possible to post non-inventory item in a Project Journal with a negative quantity. CSS also tried the same test and it worked.
![Project Journals](./project_journals.png)

## Description:
