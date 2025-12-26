Title: [Review G/L Entries] Issues with Amount to Review
Repro Steps:
Introduced by merging of a BC Idea Commit d3e83494: Merged PR 220149: Slice 558313: [Idea] Add 'Remaining amount' field to G/L en... - Reposand then with an attempt to fix it quickly https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_git/46eb6939-f5e9-495b-b6e9-976998345260/commit/c392d1ffe3ed798432820356292836ede360a68c/ It completely disrupts the feature: If you are a user who just ticks off G/L Entries and never cares about the new field Amount to Review, and you review an entry - it sets Reviewed amount to 0 (so Remaining Amount is unchanged) When you open the Review G/L Entries page, Balance is 0 (because all Amount to Review are initially 0, until you start changing them) For the review policy with Balance, the Balance check is completely off - it disregards values in Amount to Review.
Description:

