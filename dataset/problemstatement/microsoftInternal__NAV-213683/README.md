# Title: An error is generated when attempting to change (renumber) the Item No. After Posting and Generating Value Entries with Variant Codes and blank Variant Code for the Item
## Repro Steps:
In Version 26 - An error occurs when Attempting to Renumber an Item No. when the Item has Variant Codes and Item Ledger Entries and Value Entries posted for the Item and Variant Codes.
1.Create a new item - Item: Table - No: 1005
![Item Card Step1](./item_card_step1.png)
2.In the Item created add a variant=Related=item=related
![Item Card Step2](./item_card_step2.png)
Variant=GREY AND ASH
![1005 Table Step2](./1005_table_step2.png)
3.Go to item journal to get some quantities for the Item created include the variant and post each.
![Item Journals Step3](./item_journals_step3.png)
![Item Journals2 Step3](./item_journals2_step3.png)
![Message Step3](./message_step3.png)
4.Create a sale invoice for the Item TABLE without the variant and post
![Sales Invoice Step4](./sales_invoice_step4.png)
![Message Step4](./message_step4.png)
5.Create a sales invoice with Item "TABLE" include the variant and post
![Sales Invoice Step5](./sales_invoice_step5.png)
![Message Step5](./message_step5.png)
6.Make an attempt to change the item No" you receive the error message stating: You cannot rename Item No. in a Item Variant, because it is used in Value Entry.
![Error step6](./error_step6.png)
I attempted to perform more tests, and in previous versions like 25.5, I could change the Item No. without any errors.
Could this be a new change or possibly a bug?
Before
![9632 Radio](./9632_radio.png)
After
![1233 Radio](./1233_radio.png)

## Description:
Issue: An Error Occurs When Attempting to Change Item No. After Posting and Generating Item Ledger Entries and Value Entries in Version 26.0 with Items and Variant Codes involved.
The issue did not occur in Version 25.X Version or earlier. Was this a Design Change or is the an issue in the new version. If it is By Design, is there a reason for the change?
