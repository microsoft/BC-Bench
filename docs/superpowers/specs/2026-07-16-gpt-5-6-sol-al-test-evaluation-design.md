# GPT-5.6 Sol AL Test Evaluation Design

## Goal

Allow the GitHub Copilot evaluation workflow to run the existing `ALTest` custom agent with `gpt-5.6-sol`, using the minimum Copilot CLI version that supports the model while preserving benchmark reproducibility.

## Repository History

BC-Bench has consistently introduced new Copilot models by:

1. Adding the model to the `workflow_dispatch` choices in `.github/workflows/copilot-evaluation.yml`.
2. Updating the pinned `@github/copilot` npm package.
3. Updating the benchmark version in `pyproject.toml` and `uv.lock`.

Examples include commits `94e4eeb`, `02c667b`, `60e0e35`, and `8743a66`.

Commit `eb546e4` centralized the Copilot CLI pin in `.github/actions/install-eval-clis/action.yml`. Therefore, new harness updates belong in that shared action rather than directly in the evaluation workflow.

The v1.0.63 bump and subsequent revert in commits `e825aad` and `9147ec6` are on an unmerged private branch and do not define mainline practice.

## Proposed Changes

### Model selection

Add `gpt-5.6-sol` to the model choices in `.github/workflows/copilot-evaluation.yml`. Keep the existing default model unchanged so historical default runs remain comparable.

The `ALTest` custom agent remains configured in `src/bcbench/agent/shared/config.yaml`:

```yaml
agents:
  enabled: false
  name: ALTest
```

Running the experiment still requires enabling that existing agent configuration. This change only makes GPT-5.6 Sol selectable as its model.

### Copilot CLI harness

Change the shared installer pin from:

```text
@github/copilot@1.0.57
```

to:

```text
@github/copilot@1.0.70
```

Copilot CLI v1.0.70, released July 9, 2026, is the first release whose notes explicitly state "Add GPT-5.6 model support." Pin the minimum supporting version instead of v1.0.71 to avoid unrelated harness behavior changes.

Retain the repository's existing pinned npm installation method. Do not add a release-asset downloader, self-update step, or fallback installer.

### Benchmark version

Bump BC-Bench from `0.7.1` to `0.8.0` in `pyproject.toml` and regenerate `uv.lock`.

`CONTRIBUTING.md` classifies Copilot CLI bumps as minor benchmark version changes because harness behavior can affect evaluation results.

## Compatibility Review

The Copilot CLI release notes from v1.0.58 through v1.0.70 contain no removal or rename of the flags BC-Bench uses:

- `--allow-all-tools`
- `--disable-builtin-mcps`
- `--model`
- `--log-level`
- `--log-dir`
- `--prompt`
- `--no-custom-instructions`
- `--additional-mcp-config`
- `--plugin-dir`
- `--agent`

Relevant behavioral changes do not require repository corrections:

- v1.0.60 stopped resolving bare Windows executables from the working directory. BC-Bench installs required executables onto `PATH`.
- v1.0.61 began loading workspace `.github/mcp.json`. BCApps has no such file and BC-Bench does not create one; the workflow smoke test must also confirm that the internal NAV checkout does not introduce unintended MCP servers.
- v1.0.62 removed interactive input through the old background shell API. The `ALTest` agent instructions do not reference that API.
- v1.0.64 changed plugin and MCP policy handling. BC-Bench already isolates plugin configuration and explicitly controls MCP startup.
- v1.0.66 renamed the session-limit configuration key. BC-Bench does not configure session limits.
- v1.0.69 changed non-streaming prompt output behavior. BC-Bench parses metrics from stderr and session logs, not assistant stdout.
- v1.0.70 adds GPT-5.6 support without changing the invocation contract used by BC-Bench.

No compatibility code changes are required beyond the model option, harness pin, and benchmark version files.

## Validation

1. Confirm the workflow YAML exposes `gpt-5.6-sol`.
2. Confirm the shared installer pins `@github/copilot@1.0.70`.
3. Confirm `pyproject.toml` and the `bcbench` package entry in `uv.lock` both contain `0.8.0`.
4. Run the existing targeted Python tests covering Copilot invocation, model forwarding, custom-agent setup, plugin setup, LSP configuration, and metrics parsing.
5. Run pre-commit on the changed files.

## References

- [Copilot CLI v1.0.70 release notes](https://github.com/github/copilot-cli/releases/tag/v1.0.70)
- [GPT-5.6 availability announcement](https://github.blog/changelog/2026-07-09-openais-gpt-5-6-sol-terra-and-luna-are-now-available-in-github-copilot/)
- [Supported GitHub Copilot models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
