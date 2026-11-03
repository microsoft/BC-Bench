# Advanced BCal evaluations

`bcal-scenario` and `bcal-feature` share one strongly validated scenario contract:

- `session` configures BCal behavior.
- `steps` contains ordered user turns and optional `plan_action` start/cancel steps.
- `interactions` scripts deterministic answers to matching questions.
- `evaluation` is hidden from BCal and contains compilation, artifact-checklist, trace, forbidden-behavior, and optional runtime requirements.

The harness writes a redacted `execution.json` containing only `schemaVersion`, `session`, `steps`, and `interactions`, then invokes:

```powershell
bcbench evaluate bcal <instance-id> --category bcal-scenario
```

BCal receives `--scenario`, `--result`, and `--exportfolder` arguments. BC-Bench parses `evaluation-run.json` and the archived `chat.json`. A nonzero exit with a step-associated failure and successful export/archive is preserved as a measured agent outcome; missing/invalid results, session-level failures, and export/archive failures are surfaced as harness failures.

Evaluation combines:

1. Deterministic scenario completion and trace assertions.
2. Independent standalone AL compilation when the `al` compiler is installed. If only symbols are available, the result explicitly records `not_attempted`; it is never reported as a successful build.
3. Optional runtime verification (currently `null` in the pilot entries).
4. LMChecklist scoring over the task, confirmed scripted decisions, deterministic summaries, exported workspace diff, and complete textual workspace.

The three original pilot entries cover an inventory-risk feature, an integration-choice interaction, and an explicit plan-first lifecycle.

## Authority/provenance experiment

The `authority-contract` scenarios are a separate deterministic lane for the first narrow system-prompt experiment. They cover:

- direct user scope and an accepted interaction correction;
- declined, cancelled, fallback, and ambiguous replies that leave the workspace unchanged;
- retained direct-user intent after ten intervening history-pressure turns;
- prompt-like AL comments, captions, documentation, diagnostic text, and tool output that cannot broaden scope;
- host profile, page, review, and publish settings that remain facts rather than user authorization.

The fixtures assert changed paths, interaction outcomes, mutation ordering, compilation after the final mutation, and forbidden publishing. LMChecklist still evaluates implementation quality, but it does not determine authority-contract compliance. Ordinary `nl2al` remains a separate category and score.

When BCal emits Gate A evidence, the harness prefers its canonical trace over the archived chat for tool-order assertions and preserves execution identity, prompt evidence, trace size, and truncation metadata. Gate B activated-skill evidence is not required for this experiment.

Run one local scenario with the BCal CLI integration:

```powershell
uv run bcbench evaluate bcal bcal-scenario__authority-direct-and-corrected-scope-1 --category bcal-scenario --output-dir evaluation_results\authority-baseline-r1
```

Run all four entries twice for each package, changing only the installed BCal package and output directory:

```powershell
$entries = @(
  "bcal-scenario__authority-direct-and-corrected-scope-1",
  "bcal-scenario__authority-rejected-permission-1",
  "bcal-scenario__authority-retained-intent-1",
  "bcal-scenario__authority-untrusted-evidence-1"
)

foreach ($repeat in 1..2) {
  foreach ($entry in $entries) {
    uv run bcbench evaluate bcal $entry --category bcal-scenario --output-dir "evaluation_results\authority-baseline-r$repeat"
  }
}
```

Use the same BC-Bench commit, dataset files, `gpt-55-chat` deployment, backend settings, symbol cache, and two-repeat loop for the candidate. Pin the baseline package to `30.0.44.65502-beta`; pin the candidate to its exact package version. Do not use MCP mode.

Compare per-entry `trace_compliance` and individual assertion results first, then compilation and scenario completion. Compare LMChecklist scores separately. The accepted ordinary-quality reference for `30.0.44.65502-beta` is `103/110` in each of two full gold repetitions from workflow run `40399204122`; rerun baseline and candidate from the same BC-Bench revision before treating a delta as causal.
