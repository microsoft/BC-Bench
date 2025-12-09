# Fix [Bug]: External File Storage - The record in table File Account Content already exists

<!-- Thank you for submitting a Pull Request. If you're new to contributing to BCApps please read our pull request guideline below
* https://github.com/microsoft/BCApps/Contributing.md
-->
#### Summary <!-- Provide a general summary of your changes -->
Implement parsing of BlobReferences to allow working with delimter.
This will increase the perfomance of the storage browers and allows to navigate throw blob strages with more than 500 files in a "folder".

#### Work Item(s) <!-- Add the issue number here after the #. The issue needs to be open and approved. Submitting PRs with no linked issues or unapproved issues is highly discouraged. -->
Fixes #5204


Fixes [AB#610576](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/610576)


