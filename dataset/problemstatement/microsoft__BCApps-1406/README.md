# GetNextNo should error when line is closed, not take a number from an earlier line

<!-- Thank you for your contribution to BCApps! For newcomers, please ensure you've read our [Pull Request Guidelines](https://github.com/microsoft/BCApps/Contributing.md). -->

### Summary
This PR addresses a bug in the `GetNoSeriesLine` function where it failed to properly handle closed lines. Previously, if a line for a specific month was closed, the system would incorrectly issue a number from a prior month instead of signaling an error. This fix ensures that an error is thrown as expected in such scenarios, aligning with the intended behavior when dealing with closed series lines.

### Work Item
- Fixes [AB#538011](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/538011)


