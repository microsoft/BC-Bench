# [Word Template] Fix unexpected behavior of AddUnrelatedTable

<!-- Thank you for submitting a Pull Request. If you're new to contributing to BCApps please read our pull request guideline below
* https://github.com/microsoft/BCApps/Contributing.md
-->
#### Summary
This change addresses two issues that were present in the AddUnrelatedTable method.
  1. The result of the implementation method call is returned so that callers know if the record was successfully added.
  2. The "Word Templates Related Table" record that is created has the word template code assigned to it that was provided by the caller.

#### Work Item(s) <!-- Add the issue number here after the #. The issue needs to be open and approved. Submitting PRs with no linked issues or unapproved issues is highly discouraged. -->
Fixes #3105 


Fixes [AB#567861](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/567861)




