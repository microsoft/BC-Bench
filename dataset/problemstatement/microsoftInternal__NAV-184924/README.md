Title: [master] New AR rolecenter: A/R Balance must exclude BU entries
Repro Steps:
The new wide cue for A/R balance will include entries coming from consolidation But the Total Outstanding (LCY) cue only contains invoices in the current company. To make it useful even when a non-empty company is used for consolidation we must exclude entries where business Unit Code <> '' for the A/R Account Balance cue
Description:

