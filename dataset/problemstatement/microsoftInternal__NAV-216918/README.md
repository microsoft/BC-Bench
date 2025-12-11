# Title: Incorrect Non-Deductible VAT amount in project ledger entry if project has a foreign currency
## Repro Steps:

## Description:
Got it from Yammer:
Hope you are well. We have a new issue with non-deductable VAT in connection with project module that you should probably get fixed rather soon.

The column VAT amount in eg. a general journal line is always connected to the source currency of the line, but when BC is adding the "VAT Amount" to the Project Ledger Entry in the posting process, it's being added without taking into consideration currency code of the project. What if the project posted to is running in different currency?

I can tell you it sadly goes completely wrong, and I'm setting here with a year-end situation at a customer where I now have to manually correct 100s of Project Ledger Entries.

I'm fixing it myself for this client, but would be nice if you can take a look at this.

For a test.

Make a project in EUR currency. Then make a gen. journal line with a document in LCY (eg. DKK) currency with non-deductable VAT setup and notice how it goes wrong when posting preview, that it just adds the "DKK" VAT amount to the project ledger entry unit cost (EUR).
