Title: [E-Documents] Received non-linked documents errors are not visible in the tile for matching
Repro Steps:
Create new E-Document with the no PO number or with PO number doesn't exist in the BC. This document will have Error status in Document Status field and the Imported document processing error in the E-Document Status field. This document is not in the list when we look at the Waiting Purchase E-Invoices tile, as there is list of documents only filtered by the Electronic Document Status = In Progress. And it is not possible to be in the progress if there are not connections with purchase orders or some other things are missing.
Description:
Add the Error status to the Waiting Purchase E-Invoices tile filters, as all not-linked E-documents should be presented there. Currently this tile is useless.
