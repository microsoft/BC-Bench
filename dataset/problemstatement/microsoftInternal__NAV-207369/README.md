Title: [master] [ALL-E] Error message when adding a sales line with type Item that have extended text in version 25
Repro Steps:
Create an item / use an existing item. Add extended texts for this item. Set “Automatic Ext. Texts” to TRUE: Create a sales order. Create a line for the item. Extended texts are added: Change “Type” of second line to Item and enter Item No. again You’ll get the following error: Error : The record in table Sales Line already exists.
Description:

