Title: Posted Bank Deposit Line doesn't show when there's a line that equals the total of the amount
Repro Steps:
Post this:It will show only one line after posted.The problem is that in the Posted Bank Deposit Lines we store the Bank Ledger Entry of the lump sum, to find this entry we subscribe on the entries being posted and if the amount matches the total, we consider it to be the Bank Ledger Entry.A possible fix is to consider other parameters to identify the lump sum entry, possibly the GLAcc. of the entry being the Bank Account Posting Group's GL Acc.
Description:
Backport to 24.x
