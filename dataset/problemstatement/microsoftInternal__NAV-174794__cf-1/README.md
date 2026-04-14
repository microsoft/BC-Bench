# Title: Allow Multiple Posting Groups setting is ignored during Finance Charge Memo posting
## Repro Steps:
**Detailed Repro**

This was reproduced on a SE environment V23.3 (Same as cx environment), but it is a W1 issue.
Also reproduced in other country versions (ES)
![Troubleshooting](./troubleshooting.png)

>>> go to `Sales & Receivables Setup` - the Allow Multiple Posting Groups setting is ignored during Finance Charge Memo posting.
![Sales & Receivables Setup](./sales-receivables-seutp.png)

>>> Go to customer card to enable Allow multiple posting group. Also take note of the Customer posting group
![Customer Card](./customer-card.png)

>>> Go to "customer Posting Groups" CPG >> On INRIKES >> Related >> Alternative Groups
![Customer Posting Groups](./customer-posting-group.png)

![Alternative Customer Posting Groups](./alternative-customer-posting-groups.png)

From the Screenshot above we can see that UTRIKES and INRIKES has different G/L Acct in the Receivables Account.

>>> Go to Fin charge Memo
![Finance Charege Memo](./finance-charge-memo.png)

Fill the fields as shown in the image above then click on Issue, a wizard should pop up click okay.

==================
ACTUAL RESULTS
==================
The Allow Multiple Posting Groups setting is ignored, so the posting group from the header is not applied.

==================
EXPECTED RESULTS
==================
The Allow Multiple Posting Groups setting should control whether alternate posting groups are used during Finance Charge Memo posting.
