# [Subcontracting] Block Cancel of purchase invoice with subcontracting item charge (Bug 637502)

Fixes [AB#637502](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/637502)



Cancelling a Posted Purchase Invoice whose Item Charge is split between a regular item receipt line and a subcontracting service receipt line silently skipped the capacity portion. `CopyDocumentMgt.CopyFromPurchLineItemChargeAssign` rebuilds assignments by iterating Value Entries and looking up the linked Item Ledger Entry; subcontracting item-charge Value Entries have `Item Ledger Entry No. = 0` (only `Capacity Ledger Entry No.` is set), so they were dropped and the orphaned amount was redistributed to inventory entries, corrupting inventory cost.



Until a proper reversal path exists in BaseApp, this PR narrows the blast radius from the Subcontracting App:



- `SubcItemJnlPostLineExt`: in `OnBeforeInsertCapValueEntry`, populate `ValueEntry."Item Charge No."` from `ItemJnlLine."Item Charge No."` when `ItemJnlLine."Subc. Item Charge Assign."` is set, so capacity-side Value Entries carry the item charge they came from.

- `SubcPurchPostExt`: subscribe to `Correct Posted Purch. Invoice.OnAfterTestCorrectInvoiceIsAllowed` and block Cancel/Correct when the posted invoice has any Value Entry with `Item Charge No. <> ''` AND `Capacity Ledger Entry No. <> 0`. Plain subcontracting invoices are unaffected.

- Add integration test `CancelInvoiceWithSubcontractingItemChargeIsBlocked` reproducing the bug repro (mixed regular + subcontracting receipt charge assignment) and asserting the block fires.
