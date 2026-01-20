Title: [master] Sales lines suggestion - Keep it wont insert Extended text if assigned to inserted item
Repro Steps:
https://www.yammer.com/dynamicsnavdev/threads/2743753251069952Make sure item has extended text created and configured to be insered automatically into sales document (try create sales order for any customer and add the item, notice system will also insert lines of type comment) Now search for this item via Sales Lines suggestions. Choose Keep It. Item transferred to the sales line, but extended text is not. Dev hint from Yammer:It's a difference if you validate "No." in sales- or purchase- line or enter it manually in a document line. There are some important functions in the "No."- OnValidate- triggers in Document Subforms. Inserting Extended Texts is one, creating Assembly Orders another.
Description:

