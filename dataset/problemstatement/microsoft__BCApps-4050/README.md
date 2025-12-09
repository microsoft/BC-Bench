# [Performance Scheduler] Allow scheduling profilers for all user types except external

<!-- Thank you for submitting a Pull Request. If you're new to contributing to BCApps please read our pull request guideline below
* https://github.com/microsoft/BCApps/Contributing.md
-->
#### Summary <!-- Provide a general summary of your changes -->
Recent change to show user name instead of ID in the scheduler card regressed ability to schedule for external users. That is because the user lookup page filters out external users. Added an API to the facade to not filter out external users.

#### Work Item(s) <!-- Add the issue number here after the #. The issue needs to be open and approved. Submitting PRs with no linked issues or unapproved issues is highly discouraged. -->
Fixes [AB#591223](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/591223)







