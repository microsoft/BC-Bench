---
layout: default
title: BCal runtime evaluation
---

# BCal runtime evaluation

BC-Bench keeps **agent runtime** separate from **inference provider**. `legacy`
remains the default for `run bcal`, `evaluate bcal`, and `redteam scan`.
`copilot-sdk` is an explicit experimental selection and requires an SDK-enabled
BCAL package. This integration does not enable production Workspace APIs, switch
the default, or establish that the SDK meets an evaluation acceptance gate.

## Runtime and provider configuration

| Option / environment variable | Meaning |
|---|---|
| `--agent-runtime` / `BCAL_AGENT_RUNTIME` | `legacy` or `copilot-sdk`; default `legacy` |
| `--sdk-provider` / `BCAL_SDK_PROVIDER` | Explicit SDK provider type: currently `openai`, Responses only |
| `--sdk-base-url` / `BCAL_SDK_BASE_URL` | Provider base ending in `/v1`; HTTPS, or HTTP on loopback only |
| `--sdk-model` / `BCAL_SDK_MODEL` | Explicit main SDK wire model |
| `--sdk-api-key-env` / `BCAL_SDK_API_KEY_ENV` | Name of the populated environment variable holding the key, not the key itself |
| `--sdk-reasoning-effort` / `BCAL_SDK_REASONING_EFFORT` | Optional explicit `none`, `low`, `medium`, `high`, `xhigh`, or `max` |
| `--sdk-max-model-requests` / `BCAL_SDK_MAX_MODEL_REQUESTS` | Positive actual upstream HTTP admission cap, including retries/compaction; not tool calls or response iterations |
| `--sdk-timeout-seconds` / `BCAL_SDK_TIMEOUT_SECONDS` | Positive SDK deadline, shorter than Bench's outer process timeout to allow cleanup |
| `--inference-provider` / `BCAL_INFERENCE_PROVIDER` | Required non-secret main provider identity for SDK attribution |
| `--llm-backend` / `BCAL_LLM_BACKEND` | Legacy/auxiliary `external-command` (default) or `azure-openai` |
| `--llm-command` / `BCAL_LLM_COMMAND` | Required only for `external-command` |
| `--llm-endpoint` / `BCAL_LLM_ENDPOINT` | Explicit HTTPS Azure endpoint; requires `azure-openai` |
| `--llm-model` / `BCAL_LLM_MODEL` | Legacy/auxiliary model; required with Azure deployment |
| `--llm-provider` / `BCAL_LLM_PROVIDER` | Non-secret legacy/auxiliary provider attribution |
| `--llm-wire-api` / `BCAL_LLM_WIRE_API` | Known legacy/auxiliary protocol, recorded as metadata only |

SDK selection does **not** disable completion assessment, app-name generation,
RDLC customization, or optional safety inference. Configure these routes
explicitly through the legacy/auxiliary options. SDK and auxiliary models may
differ. `BCAL_COMPLETION_REVIEW_MODEL` remains a separate auxiliary setting.
An external command's underlying protocol is unknown unless explicitly
attributed; it is not assumed to be Responses.

SDK provider arguments are rejected in legacy mode. Azure auxiliary configuration
cannot simultaneously contain an external command. URLs must not contain
credentials, queries, or fragments. Unset keys and incompatible settings fail
before agent execution; there is no login prompt or provider fallback.

The initial validated upstream contract uses SDK `1.0.29` and native runtime
`1.0.107`. The request budget counts upstream HTTP admissions, not response
iterations or tool calls. Detailed runtime identity and usage extraction must
follow the packaged BCAL result contract. Do not treat unavailable metrics as
measured zero.

## Private governed Responses provider

`src\bcbench\agent\bcal\bc_eval_sdk_proxy.py` is a persistent evaluation-only
transport. It binds only to `127.0.0.1`, requires a random local Bearer key,
accepts only the selected protocol route and model, and forwards Responses JSON
and SSE without conversion. It reuses the configured certificate, token
provider, taxonomy, and upstream transport; the initial sticky-route ticket is
empty and subsequent tickets are retained. The local key is never sent upstream.

Use the isolated `bc-eval==0.6.1` environment created by the workflow. Stage only
the specifically authorized evaluation certificate as a private PFX and set
`LLM_API_CERTIFICATE_FILE`; the workflow uses its existing OIDC and configured
Key Vault secret-get route. Remote certificate signing is a different permission
and is not a substitute. Never enumerate unrelated secrets or change access
permissions to make an evaluation work.

The process that starts the provider owns it and its random key. Generate the
key in that process's environment, start the provider as a child, read the
non-secret readiness file, and perform an authenticated `/health` check. Set
`BCAL_SDK_BASE_URL` to the readiness base plus `/v1` and
`BCAL_SDK_API_KEY_ENV=BCAL_SDK_PROXY_KEY`. Keep the provider alive for the entire
evaluation, then terminate its specific PID in `finally`. Never copy keys into
argv, reports, repository files, or uploaded artifacts.

The workflow starts one provider per evaluation worker, not a subprocess per
SDK response. The existing external-command bridge remains explicit and is
used separately for auxiliary inference. Its chat route also supplies the
required initial empty sticky-route header.

## Workflow and diagnostics

Dispatch `bcal-evaluation.yml` with `agent-runtime=copilot-sdk`, an **exact**
SDK-enabled `bcal-version`, the appropriate existing official/experiment feed,
and explicit `sdk-model` and auxiliary `external-model`. Scheduled runs remain
legacy. Feed selection, symbols, entry prompts, exports, and downstream judges
are unchanged. An SDK version range, `latest`, or missing version is rejected.
SDK workflow dispatch is restricted to `test-run=true` (two entries in the
selected tier), at most four concurrent workers. Use a fixed-entry/repeat
manifest for an approved bounded pilot; full-dataset SDK dispatch is not enabled.
SDK workflow defaults cap model requests at 64 and the SDK deadline at 1200
seconds, inside Bench's 1500-second process timeout. Reasoning defaults to
unset; choose an explicit supported value for controlled comparisons.

Each scenario evaluation preserves an `<instance-id>.bcal` directory containing
`console.log`, the available raw `result.json`, and a versioned `manifest.json`.
SDK redteam prompts use scenario mode too, with diagnostics under the prompt's
export directory. Redteam scans also retain a sibling `<output>.execution.json`
with BCAL version, main/auxiliary configuration and scan completion/failure.
Manifests include task-prompt SHA-256, execution attribution,
measured metrics, and terminal/failure identity. Raw runtime results retain
available usage, tool and terminal evidence. Workflow uploads include diagnostics
on success and failure, never the PFX or local key.
The packaged runtime's stable `runtimeIdentity` is grouped separately from
per-turn `agentRuntimeEvidence`; terminal outcomes, model admissions, usage,
iterations and tool calls never become grouping dimensions. SDK evidence usage
is main-only and must not be added again to combined main/auxiliary totals.
Bench reads `totals.inputTokens` and `totals.outputTokens` once, including on
failed turns. These are recorded combined subtotals, not complete governed
billing; main-only reported cost is not converted into AI credits or a total
cost. Explicitly unavailable SDK usage remains null even if placeholder totals
are zero. Aggregate tool counts use `toolUsage[].started`, never root plus
per-step counts.
Input and output availability are checked separately: a recorded output
subtotal does not turn unknown input usage into measured zero.
Failed generated AL files are retained under the diagnostic directory's
`exports` subdirectory; their presence never changes failure into success.

A zero exit is insufficient for scenario success: `completed` must be true,
steps must be present, and every step must have succeeded. Timeout, nonzero
exit, malformed/missing result, abort, unresolved input, or incomplete steps
remain agent errors even if generated AL exists. Such exports are diagnostic,
not evidence of successful task completion.
SDK runs additionally require matching runtime/model/reasoning/auxiliary
configuration, successful export, and one ordered runtime-evidence record per
user turn with `terminalState=completed` and `domainCompleted=true`.
An outer timeout terminates BCAL's owned process tree (Windows PID-targeted
`taskkill /T`, or a dedicated POSIX process group), not only the parent process.
Cleanup failures remain explicit errors with `cleanup-unverified` diagnostics;
they never count as a passing lifecycle gate.

Result summaries reject mixed BCAL runtime/provider/version/configuration
identities rather than silently using the first result's identity. Missing BCAL
usage stays null; measured zero is still zero. Do not combine pre-metadata
legacy runs with attributed SDK runs.
BCAL summary `usage_availability` records how many runs actually supplied each
averaged usage metric, so partial measurements are not presented as full coverage.
Downstream bc-eval exports carry authoritative nullable BCAL metrics and per-field
availability in versioned `metadata.agent_measurements`. Export schema `1.1`
also labels token subtotal scope and preserves each turn's
main and combined usage availability. The pinned bc-eval
`0.6.1` scorer requires numeric flat token fields for addition and price lookup;
those legacy compatibility fields can contain placeholders. Do not interpret
their token/cost estimates as measurements when `agent_measurements` marks the
underlying value unavailable. In particular, an unknown cost is not free usage.

## Paired evaluation gate

First prove the exact packaged SDK binary, streaming tool exchange, cancellation,
and cleanup on the actual evaluation host. A direct Responses request or a
headless SDK startup is not an SDK task evaluation.

Use the same existing gold/challenge entries, symbols, prompts, judges, and
explicit auxiliary configuration for both runtimes. Pin package/runtime/SDK
versions, providers, wire models, reasoning, prompt/catalog identities and
budgets. Label chat-versus-Responses and other unavoidable provider confounders.
Operational smoke outcomes do not replace downstream checklist judging or
establish statistical non-inferiority.

Agree the quality/compile margins, repeated-run scope, resource ceiling, and
hard failure/policy/cleanup gates before pilot or full evaluation. Report
unavailable usage/cost and missing redteam prerequisites explicitly. Do not
change dataset entries or judging to improve SDK results.
