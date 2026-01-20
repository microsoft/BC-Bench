Title: [master] Purchase order posting form PO list does not respect User setting Purchase invoice Posting Policy
Repro Steps:
repro steps in attached file
Description:
Issue: posting multi Purc Orders form Purc Order list does not follow PI Posting Policy. Solution: in codeunit 1380 "Batch Processing Mgt." in procedure SetParametersForPageID(PageID: Integer) we should add control of Posting Policy
