# [PEPPOL] Skip Allocation Account lines in sales document validation

### Summary

Releasing a sales document that contains a sales line of type **Allocation Account** failed PEPPOL BIS 3 validation with *"You must specify a valid International Standard Code for the Unit of Measure for ."* (empty UoM message tail). Posting the same document works.

### Root cause

`PEPPOL30 Sales Validation Impl.CheckSalesDocumentLine` calls `PEPPOL30.GetLineUnitCodeInfo`, whose `case SalesLine.Type` only handles Item, Resource, G/L Account, Fixed Asset and Charge (Item). There is no branch for `Type::"Allocation Account"`, so `unitCode` stays empty and the guard `(Type <> ' ') and ("No." <> '') and (unitCode = '')` errors.

Allocation account lines are placeholder lines that are expanded into their underlying G/L distribution lines during posting and are never themselves exported in the electronic document. Posting works because the post-time PEPPOL check iterates the *posted* lines (only G/L Account lines); the release-time check iterates the *unposted* sales lines, which still contain the allocation account placeholder.

### Fix

Skip lines of type `Allocation Account` early in `CheckSalesDocumentLine`, mirroring posting behavior. Adds a regression test (`TestPeppolValidationSalesInvoiceAllocationAccountLineSkipped`).

This mirrors the equivalent fix in the Base Application (internal Bug 632064).

[AB#632064](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/632064)




