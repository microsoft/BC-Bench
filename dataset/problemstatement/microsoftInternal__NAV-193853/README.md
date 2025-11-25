Title: [master] Incoming documents are not synced between multiple general journal lines with the same Document No. and Posting Date
Repro Steps:

Description:
Issue: One Document in two lines needs two digital documents.
Setup: CheckType = Attachment, Generated Automatically = False
Create one document in two (or more) lines. In line 1 - Debit 100, and in line 2 Credit -100. Both lines of course have equal Document No. and Posting Date.
Add an incoming document to one of the lines. Let's call this file "eDoc1".
Post (or post preview).
Error 1: You will be asked to add an Incoming Document per line!
To pass the Error message, you attach an Incoming Document to the other line. Let us call this file "eDoc2".
Post.
Now the error message disappears. However, "eDoc1" and "eDoc2" are two different files.
Result: "eDoc1" is the one document that is attached to my entries.
So why ask for a document per line?
