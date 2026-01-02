# Update delegated user plans on login

<!-- Thank you for submitting a Pull Request. If you're new to contributing to BCApps please read our pull request guideline below
* https://github.com/microsoft/BCApps/Contributing.md
-->
#### Summary <!-- Provide a general summary of your changes -->
**Problem**
Delegated plans are not updated on user sync. If they're ever changed, we do not update them.

Additionally, a delegated user can end up without any plans assigned, and will never get one assigned.

**Solution**
Update delegated user plans on login to ensure delegated users have a plan.

#### Work Item(s) <!-- Add the issue number here after the #. The issue needs to be open and approved. Submitting PRs with no linked issues or unapproved issues is highly discouraged. -->
Fixes [AB#539137](https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_workitems/edit/539137/)






