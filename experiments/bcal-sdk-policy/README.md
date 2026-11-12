# Governed BCAL policy validation

The existing `.github/workflows/bcal-evaluation.yml` dispatches the isolated
`validation-phase=preflight`, then `validation-phase=study` with the successful
same-commit `preflight-run-id`. The ordinary evaluation defaults are unchanged.
The reusable workflow and actions install BC-Bench and the exact governed BCAL
package; all experiment executions use `bcbench evaluate bcal`, the existing
NL2AL pipeline and unchanged pinned checklist scorer.

`study.json` fixes the original four smoke cases, two repeats and both policies
(16 attempts). Each of eight case/repeat workers executes its two variants
sequentially, reversing order on the second repeat; at most four workers run.
This compares legacy/BCAL planning with SDK/Copilot planning and self-review,
not source-patch A/B or pure orchestration parity.

The 8-hour aggregate grant includes preflight, setup, all worker attempts,
judge, controller and artifacts. Disjoint job reservations total 28,320 seconds;
480 seconds remain for runner/controller finalization. A worker never admits
another attempt without a full 1,500-second evaluation and separate
100-second judge reservation. GitHub's job timeouts cap each reservation.
There are no evaluation retries or default switches. Final measured accounting
must use all jobs' start/end timestamps, including failures and preflight.

The original no-model admission run
[43236707356](https://github.com/microsoft/BC-Bench/actions/runs/43236707356)
failed a redundant standalone feed read after the existing installation succeeded.
Its full 414-second job charge remains in the preflight grant; the original ref
and failed receipt are preserved. Admission now reuses the install action's exact
cached nupkg rather than introducing a second private-feed downloader. This is
not a repeated or replacement semantic attempt.

Package/source, dataset, prompts, assertions and all 350 symbol hashes are
checked before inference. The existing feed/OIDC/Key Vault actions are reused.
Main, auxiliary and judge routing use fixed-model loopback proxies with separate
memory-only sticky sessions; tickets and credentials are never retained.
Persistent legacy/judge affinity is a disclosed difference from historical local
adapters. The judge remains the exact pinned scorer, with no Braintrust/Kusto
storage.

Public artifacts contain only explicit identity, counts, booleans, measurements
and hashes. Raw AL, prompts, model/judge response text, arbitrary error text,
private packages, certificates and tickets remain ephemeral on the private
runner filesystem and are never uploaded. Therefore this study does **not**
provide durable raw-content replay. Missing or invalid evidence remains visible,
unscoreable, and prevents a complete-comparison claim.

## Local execution

The same runner works without Actions. Use Windows, Python 3.13, the locked
BC-Bench environment, the exact package in `<work>\package\package.nupkg`
and its verified extracted `stage`, and the exact symbol cache named by
`symbols.json`. Create separate inference/judge environments from the pinned
requirements files and install `bc-eval==0.6.1` from the authorized private feed
without changing those dependency versions. Supply a supported certificate
and identity using `LLM_API_CERTIFICATE_FILE`, `LLM_API_TENANT_ID` and
`LLM_API_CLIENT_ID`; `LLM_API_ENVIRONMENT` must be `TEST`. Do not copy session
credentials to CI.

Set `BCAL_STUDY_WORK`, `BCAL_STUDY_INFERENCE_PYTHON`,
`BCAL_STUDY_JUDGE_PYTHON` and `PYTHONPATH=<checkout>\src`. Then:

```powershell
.\.venv\Scripts\python.exe .\scripts\bcal_governed_study.py matrix
& $env:BCAL_STUDY_INFERENCE_PYTHON .\scripts\bcal_governed_study.py preflight --work $env:BCAL_STUDY_WORK --output <sanitized-directory>
.\.venv\Scripts\python.exe .\scripts\bcal_governed_study.py pair --pair <0-7> --work $env:BCAL_STUDY_WORK --output <sanitized-directory>
```

Each physical pair requires an exclusive admission and resource reservation;
these commands are **not** permission to rerun this study or resume the paused
historical pilot. Preserve the existing local pilot drivers, lock, raw evidence,
invalid-original/replacement linkage and ledger separately. An authorized local
study additionally requires a supported process-scoped keep-awake mechanism and
wall-clock watchdog; the hosted workflow uses disposable managed runners.
