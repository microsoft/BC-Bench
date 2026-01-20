Title: [master] [ALL-E] When creating a new price for variant items the variant code should not automatically display in the price list based on the previously created line
Repro Steps:
Open BC 22.13 W1 Search for "Feature management"Activate "New sales pricing experience" Search for ItemsCreate a new item Create 3 Variants for this item:Actions -> item -> variants Search for "Sales price lists"Create a new price listInsert a line with your new item (70061) and select a variant "Blue"insert a second line for this item (70061) the variant "Blue" is automatically presettedACTUAL RESULT:the variant "Blue" is automatically presetted EXPECTED RESULT: The Variant should not be preset for the next line.
Description:

