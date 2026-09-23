# [ALL-E] Report 152 "Calculate Low Level Code" terminates with error: "Cannot add instance as another with key %1 has already been added." after upgrade to v28.1

## Repro Steps

\*\*Issue Description:\*\*
Report 152 (Calculate Low Level Code) terminates with error: "Cannot add instance as another with key {"Type":"Production BOM","No.":"BM00780"} has already been added." after user update to 28.2. The same error didn't occur on version 27.5
\*\*AI suggested epro steps\*\*
The duplicate scenario
----------------------
`PopulateFromSKUAndRelatedBOMs` can produce the same `Item → Production BOM` relation as `PopulateFromItemAndRelatedBOMs` whenever an SKU's `Production BOM No.` equals the Item's own `Production BOM No.` (or another SKU already pointed at that pair). More broadly, both procedures build `Item → Prod BOM` edges, so their outputs overlap by design.
That overlap on its own shouldn't error, because LowLevelCodeCalculator.Codeunit.al:253-262 guards with `BOMStructure.ChildHasKey(Parent, Child)`, and `AddRelation` in BOMTreeImpl.Codeunit.al:14-33 uses `TryGet` before inserting into `AllNodes`. So the guard should catch every duplicate.
Run the report 152 (Calculate Low Level Code)
![image.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/cdaf9b07-63d3-4563-9c15-affa67f75298?fileName=image.png)

## Description

Check the [Incident-51000001103799 Details - IcM](https://portal.microsofticm.com/imp/v5/incidents/details/51000001103799/summary) for more details.
