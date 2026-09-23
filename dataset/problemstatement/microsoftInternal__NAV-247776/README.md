# [master] [ALL-E] Item Extended Text gets deleted if you modify the item description in Sales Quote an Purchase Quote

## Repro Steps

REPRO:

==============

Go to Items

Open item 1896-S

Go to Related - Item - Extended Text and add a new Extended TExt.

Open a Sales Quote or a Purchase Quote.

Create a new Sales Quote or a Purchase Quote

Add an Item 1896-S to the lines

* Select the item line and click Insert Ext. Texts to populate the extended text lines.
*

* Modify the Description field of the main item line from e.g. ATHENS Schreibtisch to ATHENS Schreibtisch2
*

* Validate the field (press Enter or move out of the field).
*

*

*
EXPECTATION:

==============

Like in all other sales or purchase documents the extened text should stay

RESULT:

==============
After validation, observe that the extended text lines are automatically deleted.
