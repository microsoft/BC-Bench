# Title: [Subcontracting] Standard Task not propagated from Routing to Prod. Order Routing or Subcontracting Worksheet; prices not picked up
## Repro Steps:
![Image](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_apis/wit/attachments/10f744c3-9170-4590-8dd3-cf148b602b4a?fileName=image.png)

## Hints:
### Repro Steps
**Summary**: The Subcontracting app needs to be aligned with changes made to the "Description 2" field on various tables. The bug description contains inline screenshots showing the field changes but minimal textual detail.

#### Steps to Reproduce
1. Open Business Central with the Subcontracting module enabled.
2. Identify all tables in the Subcontracting app that reference or use the "Description 2" field (e.g., Item, Production Order Line, Purchase Line, or other related tables).
3. Check that the Subcontracting app properly reads, writes, and displays the "Description 2" field wherever it is used in the base BC application.
4. If "Description 2" has been modified (renamed, repositioned, or had its properties changed) in the base tables, verify that:
   - All Subcontracting page extensions show the updated "Description 2" correctly.
   - All Subcontracting codeunits that reference "Description 2" are aligned with the new field definition.
   - All API queries or pages that expose "Description 2" reflect the changes.
5. Look for compilation errors or runtime issues caused by the misalignment.

#### Expected Result
- The Subcontracting app should be fully aligned with any changes to the "Description 2" field in the base BC application.
- No compilation errors or data integrity issues related to this field.
-
#### Actual Result
- The Subcontracting app references are not aligned with the "Description 2" field changes, as shown in the inline screenshots.
-
#### Additional Context
- Related to
620425 [Subcontracting] "Single Instance Dictionary" is a very generic name. Rename & refactor it appropriately (SingleInstanceDictionary naming/refactoring).

#### Self-Review
- The repro steps cover the general alignment concern but specific tables/pages affected are documented in the screenshots only.
- This is a code alignment/compatibility issue following upstream changes.

**Score: 5/10** - The bug description is primarily screenshots with limited textual context. Steps provide a reasonable framework for verification.

[AI-REPRO] score=5 | workItemId=620556 | generated=2026-03-25 | sources=Title,Description (inline images)
