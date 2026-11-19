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

BCal receives `--scenario`, `--result`, `--exportfolder`, and `--include-evidence` arguments. The complete `evaluation-run.json` is captured through the shared harness transcript channel introduced for one-step BCal evaluation. Deterministic trace assertions read the structured evidence events from that transcript; the advanced categories do not maintain a separate chat-archive parser. A nonzero exit with a step-associated failure and a successful export is preserved as a measured agent outcome, while missing/invalid results, session-level failures, and export failures are surfaced as harness failures.

Evaluation combines:

1. Deterministic scenario completion and trace assertions.
2. Independent standalone AL compilation when the `al` compiler is installed. If only symbols are available, the result explicitly records `not_attempted`; it is never reported as a successful build.
3. Optional runtime verification (currently `null` in the pilot entries).
4. LMChecklist scoring over the task, confirmed scripted decisions, deterministic summaries, exported workspace diff, and complete textual workspace.

The three pilot entries cover an inventory-risk feature, an integration-choice interaction, and an explicit plan-first lifecycle.
