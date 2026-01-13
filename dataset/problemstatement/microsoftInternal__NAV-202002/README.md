Title: [master] When changing Ship-to code on sales order the salesperson code is overwritten
Repro Steps:
-----> Create a new sales order The initial Salesperson Code after I added a Customer No is DH. ---> change the Salesperson Code to a different one Change the Ship-to to custom Look back to the Salesperson Code, which was changed to JH, it has been reverted to DH This was not the behavior in version 23.5 When the Ship-to Address is changed to Custom it does not affect the Salesperson code. Additional Information:The Salesperson Code on the Sales Order page shows DH. But if you check the Dimension Set Entries, the Salesperson Code shows JH.
Description:
an issue with the salesperson code being overruled when making a new sales order Business Central. This problem started after a new version was implemented, as previously the salesperson code entered at the start was not affected by other changes
