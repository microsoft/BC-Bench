---
name: update-agent-harness
description: "Update an agent harness used by BC-Bench. Use when bumping GitHub Copilot CLI or Claude Code, reviewing intervening release notes and breaking changes, curating benchmark-worthy model choices, updating the BC-Bench version, or preparing the release handoff."
---

# Update Agent Harness

Treat harness updates as benchmark changes. Work manually; do not create workflows, branches, pull requests, tags, or releases unless explicitly asked.

## Workflow

1. **Scope:** Check `git status`, identify the current pin in `.github/actions/install-agent-harnesses/action.yml`, and search for all version, model, and default references. Use the latest stable GitHub release unless the user names another version.
2. **Research:** Read every intervening first-party GitHub release note. Assume the selected stable release is available on npm; do not gate the update on npm publication metadata or change the installation method. Compare changes against BC-Bench's flags, authentication, prompt mode, exit behavior, sandboxing, MCP/LSP/hooks/plugins, output parsing, debug logs, and model IDs. Resolve required compatibility changes before bumping the pin.
3. **Curate models:** Availability is only a candidate signal. Include models that add a frontier baseline, distinct provider/family, useful cost or speed tier, stable successor, or specific experiment. Exclude superseded, redundant, preview/unstable, unverified, or low-value models. Prefer one representative per role.
4. **Edit:** Change only the version in the existing workflow/action npm install command; do not change how the harness is installed. Update required compatibility code, synchronize curated models across the Python `Literal`, workflow choices, command defaults, and judge configuration, then search for stale references. Harness or model changes normally require a minor version bump in `pyproject.toml`; follow `CONTRIBUTING.md` for exceptions.
5. **Validate and report:** Verify the installed version and flags, run focused harness tests and `uv run pre-commit run --all-files`, and run the full suite when compatibility code changed. A test evaluation using the evaluation identity is required before a full run; hand it off when credentials or infrastructure are unavailable. Report version changes, model decisions, release-note impacts, checks run, and remaining risks.

## Model Decisions

Model visibility varies by plan, policy, region, rollout, and token. Record the identity used for live discovery and mark availability unverified when the evaluation identity cannot be checked.

Do not remove a model merely because one account cannot see it. Require official retirement, confirmed evaluation-account failure, a clearly preferred successor, or an explicit maintainer decision. Never delete historical results.

Use this table when the model set changes:

| Model | Availability evidence | Benchmark role | Decision | Rationale |
|---|---|---|---|---|

## Copilot Surfaces

- `.github/actions/install-agent-harnesses/action.yml`
- `src/bcbench/agent/copilot/agent.py` and `metrics.py`
- `src/bcbench/agent/copilot/cli.py` and `src/bcbench/cli_options.py`
- `.github/workflows/copilot-evaluation.yml`
- `.github/workflows/contamination.yml`
- Defaults under `src/bcbench/commands/` and `src/bcbench/config.py`
- Copilot-focused tests under `tests/`

Preserve unrelated changes and stored leaderboard results. Stop for maintainer input when release notes are incomplete, compatibility affects result comparability, a model has no clear benchmark role, availability is required but unverified, or focused validation fails.
