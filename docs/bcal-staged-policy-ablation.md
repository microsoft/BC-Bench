# Staged BCal policy ablation

This study uses deterministic BCal repository tests as the policy-fixture lane. It does not add a live policy-fixture category or workflow.

The focused live matrix uses the checked-in `bcal-staged-policy-ablation-gold` and `bcal-staged-policy-ablation-challenge` cohorts. Each contains the union of original-problem and suspected-regression cases, with per-case applicability for BCal PRs `8656`, `8669`, and `8735`.

Run these package variants with fixed generation, completion-review, and judge settings:

- `M`: common baseline.
- `A-off`: disable only the `8656` discovery cutoff.
- `B-off`: disable only the `8669` blocker-batching and handover guidance.
- `C2-fix`: correct or disable only the `8735` immediate checklist-only structured-blocker exit.

Each package/cohort combination runs three independent repetitions. The focused matrix is 4 variants x 2 cohorts x 14 cases x 3 repetitions = 336 case-runs across 8 workflow dispatches. Do not dispatch until exact package handoffs provide the package version and the common-base and variant-patch SHAs.

Analysis is paired by shared case and repetition. Compare only rows present for both variants; a missing row is missing coverage, not an improvement. Report coverage, compile facts, terminal/lifecycle classes, and targeted failure rates using each row's applicability and target/control role.

Only a variant with credible benefit on its applicable original-problem cases and no clear control regression advances. The promotion lane runs the baseline and promoted variant on full gold and full challenge, each twice. With the current 110 gold and 65 challenge cases, that is 700 case-runs per promoted variant comparison across 4 workflow dispatches. Do not run a live `BC-off` diagnostic unless the `8669` effect remains non-identifiable after the focused matrix.
