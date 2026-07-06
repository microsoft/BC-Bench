# Design: Marketplace & Local Plugins as an Experiment Toggle

- **Date:** 2026-07-03
- **Status:** Approved (design); pending implementation plan
- **Category impact:** None (agent-setup only; applies to all categories)

## 1. Summary

Add a config-driven experiment toggle that installs agent **plugins** — from a
marketplace pinned to a git commit, or from a local folder — into the running
CLI, so their skills are native during a run. This lets us measure whether a
plugin improves benchmark performance, alongside the existing
instruction/skill/agent/MCP toggles.

Activation uses each CLI's **real plugin commands** (`plugin marketplace add` +
`plugin install`), run as ordinary subprocess calls in the setup phase **before**
launching the agent. This is deliberate: declarative `extraKnownMarketplaces` /
`enabledPlugins` config is processed only via the interactive trust dialog and is
**ignored in headless mode** — which is exactly how BC-Bench invokes both CLIs
(`copilot -p`, `claude --print`) — so it cannot be used (see §2.3). To pin a
commit we clone the marketplace ourselves into `<repo>/.bcbench/` and add it as a
**local** marketplace. Multiple plugins can be enabled at once.

Because installs go to the CLI's **user-scope** store (project scope is ignored
headless) and execution-based categories run entries as a **parallel matrix on a
shared self-hosted runner** (see §2.5), each entry redirects the CLI's config home
to a **per-entry isolated directory** (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under
`<repo>/.bcbench/`) for both the install commands and the agent launch. This makes
concurrent entries independent (no shared global state, no cross-entry race) and
**removes the need for teardown** — the isolated home is discarded with the
checkout. Auth in the fresh home comes from the env token the workflow already
sets (`COPILOT_GITHUB_TOKEN`; `ANTHROPIC_API_KEY`). Cloned content lives under
`.bcbench`; installed plugins are recorded in `ExperimentConfiguration`.

## 2. Background

### 2.1 Experiment model
Experiment levers live in `agent/shared/config.yaml` and are applied by
`operations/*` setup functions inside the agent runners
(`agent/copilot/agent.py`, `agent/claude/agent.py`) **before** the CLI subprocess
launches; each returns a value folded into `ExperimentConfiguration`, persisted
with the result. Between-run isolation comes from `clean_repo` (`git reset --hard`
+ `git clean -fd`) plus each setup function cleaning before it writes.

### 2.2 Existing `.bcbench` plumbing to reuse (PR #651, commit `7eab2f9`, Haoran)
`agent/shared/plugin.py` provides `_PLUGIN_ROOT = Path(".bcbench")`,
`write_agent_plugin(...)` (creates dirs; `.bcbench` is created at run time, not
committed), and `remove_agent_plugin(repo_path, folder)` (clean-before). This
design reuses that runtime-created, repo-local root to hold cloned marketplace
content.

### 2.3 Why the commands (config injection does not work headless)
Verified empirically **and** corroborated by an independent investigation
(gist `alexey-pelykh/566a4e5160b305db703d543312a1e686`):

- Declarative `extraKnownMarketplaces` + `enabledPlugins` in project/repo settings
  (`.claude/settings.json`, `.github/copilot/settings.json`) is processed **only
  during the interactive trust-dialog handler**. In headless mode (`-p` /
  `--print`) the trust dialog is skipped, so the config is **never processed**.
  - My tests: repo-local `.github/copilot/settings.json` made a marketplace show
    in `plugin marketplace list`, but a real `copilot -p` session did **not**
    auto-install it (the plugin's skill never loaded; `installed-plugins/`
    unchanged before/after).
  - Plugin commands read from separate user-level storage
    (`~/.claude/plugins/known_marketplaces.json` / `installed_plugins.json`;
    `~/.copilot/config.json` `installedPlugins` + `settings.json`), which is where
    `plugin install` writes.
- **Project scope is also ignored headless**, so `--scope project` does not help.
  Both CLIs must install at **user scope**.
- Hand-writing those user-storage files is brittle (undocumented schema); the
  documented, robust path is the CLI commands. **Decision: use the commands.**

### 2.4 CLI facts (verified live on this machine)
Copilot CLI `1.0.69-0`, Claude Code `2.1.161`.

- Full Copilot lifecycle against a **local** marketplace (a dir with
  `.claude-plugin/marketplace.json` + a plugin with `.claude-plugin/plugin.json`),
  non-interactive, offline, exit 0 each:
  - `copilot plugin marketplace add <local path>` → "Marketplace added successfully."
  - `copilot plugin install <plugin>@<marketplace>` → "Plugin installed successfully. Installed 1 skill."
  - `copilot plugin uninstall <plugin>` / `plugin marketplace remove <marketplace>` → success; baseline fully restored.
- Marketplace source accepts a **local path** (the marketplace ROOT — the dir
  containing `marketplace.json`); the CLI records a local source as
  `{"source":"directory","path":…}`. The plugin is selected `<plugin>@<name>`
  where `<name>` is the `name` inside `marketplace.json`. Copilot reads the
  catalog from `.github/plugin/marketplace.json` or `.claude-plugin/marketplace.json`.
- Neither CLI has a `--ref`/`--commit` flag → we pin by cloning ourselves.
- Claude exposes the same command set (`plugin marketplace add|remove`,
  `plugin install|uninstall`); use default **user** scope (see §2.3).
- Agent launch, model, MCP, and permissions are still passed as explicit flags;
  the agent command line is unchanged apart from the config-home env var (§2.5).
- **Per-entry isolated home works headless (verified):** with a fresh
  `COPILOT_HOME`, `plugin install` succeeds, `copilot skill list` shows the
  plugin's skill (content loads), and a real `copilot -p` session runs (exit 0,
  auth via `COPILOT_GITHUB_TOKEN`) with no onboarding block; the real `~/.copilot`
  is untouched. Fresh `CLAUDE_CONFIG_DIR` isolates install the same way.

### 2.5 Concurrency: why a per-entry isolated config home
Execution-based categories (`bug-fix`, `test-generation`) run entries as a
**parallel matrix** (`max-parallel: 64` in `copilot-evaluation.yml`) on the
self-hosted `GitHub-BCBench` runner, where legs can share a machine. The CLI's
plugin store is **user scope / global** (`~/.copilot`, `~/.claude`) — the first
experiment lever to touch shared state (instructions/skills are repo-local, MCP is
a per-invocation flag, AL-LSP is repo-local `.bcbench`). Concurrent entries would
therefore race: two `plugin install`s writing the same global config, or one
entry's cleanup removing a marketplace/plugin an in-flight entry still uses.

Fix: each entry redirects the CLI config home to a **unique per-entry directory**
(`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` = `<repo>/.bcbench/<agent>-home`) for both
the plugin commands and the agent launch. Installs are then fully isolated per
entry, eliminating the race and **removing any need for teardown** — the home is
ephemeral (fresh checkout per matrix leg; cleaned before each run locally). Fresh
GitHub-hosted VMs (`code-review` on ubuntu-latest, `nl2al` on windows-latest) are
already isolated, but the per-entry home is applied uniformly.

## 3. Goals / Non-goals

### Guiding principle
Keep it simple and reuse existing architecture. Use the CLIs' documented commands
rather than reverse-engineering config or fighting the headless trust gate. Keep
everything repo-local under `.bcbench` (cloned content **and** the per-entry
config home), so concurrent entries never share state and there is nothing global
to tear down.

### Goals
- Config-driven, per-entry enable/disable, multiple plugins at once.
- Marketplace plugins pinned to a git commit (reproducible); local plugins too.
- Plugins installed by name via the CLI's real commands, on Copilot and Claude.
- Concurrency-safe: per-entry isolated config home; no shared global state.
- No teardown and no residue in the developer's real config.
- Installed plugins recorded in `ExperimentConfiguration`.

### Non-goals
- Changing/migrating the AL-LSP plugin (left as-is).
- Selecting which plugin agent *drives* the run (existing `--agent` covers it).
- Relying on `extraKnownMarketplaces`/`enabledPlugins` injection (ignored headless).
- Hand-writing CLI storage files (undocumented schema — use the commands).
- Dataset, category, or scoring changes.

## 4. Design

### 4.1 Flow (mirrors the existing setup_* functions)
New `operations/plugin_operations.py`:

```python
def setup_plugins_from_config(
    agent_config: dict, entry: BaseDatasetEntry, repo_path: Path,
    agent_type: AgentType, cli_cmd: str,
) -> tuple[list[str], dict[str, str]]: ...
    # returns (plugin_records, env_overrides)
```

`setup_plugins_from_config` creates a fresh per-entry config home under
`.bcbench`, clones/copies enabled plugins under `.bcbench`, runs `marketplace add`
+ `install` **into that home** (via `env`), and returns:
- `plugin_records`: `["<name>@<commit>", "<name>@local", …]` for the result, and
- `env_overrides`: `{"COPILOT_HOME": …}` / `{"CLAUDE_CONFIG_DIR": …}` (empty when
  no plugin is enabled) that the runner merges into the agent-launch environment.

There is **no** `teardown_plugins`: the isolated home is discarded with the
checkout, and a clean-before at the top of setup removes any stale home.

### 4.2 Materialize content into `.bcbench/`
- **Clean before:** inline-`rmtree` `<repo>/.bcbench/plugins` and the per-entry
  config home (do NOT import `remove_agent_plugin` — `operations` must not import
  `bcbench.agent`, which would create a cycle). Then recreate both fresh.
- **marketplace** (`repo` + `commit`): shallow-clone into
  `<repo>/.bcbench/plugins/<slug>` and `git checkout <commit>` (`clone_at_commit`).
  Read the marketplace `name` from its `marketplace.json`.
- **local** (`path`): copy into `<repo>/.bcbench/plugins/<slug>`. `path` resolves
  under `src/bcbench/agent/shared/instructions/<sanitized-repo>/` and must be a
  marketplace root (contains `marketplace.json`).
- Failures raise `AgentError`.

### 4.3 Install via the CLI commands (into the per-entry home)
With the config-home env var set to the per-entry directory, for each enabled
entry using the resolved CLI binary:
- `<cli> plugin marketplace add <repo>/.bcbench/plugins/<slug>`
- `<cli> plugin install <plugin>@<marketplace-name>` for each requested plugin
- All plugin commands run with `env={**os.environ, <home-var>: <home>}`; failures
  raise `AgentError` (after best-effort removal of the partial home).

### 4.4 Isolation & cleanup (no teardown commands)
- The per-entry config home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` =
  `<repo>/.bcbench/<agent>-home`) makes every entry's marketplace/plugin state
  private; concurrent matrix legs never collide, and there is nothing global to
  undo.
- Cleanup is the clean-before `rmtree` of `.bcbench/plugins` + the home at the
  next run, plus `git clean -fd` / fresh checkout. The developer's real
  `~/.copilot` / `~/.claude` is never touched.
- Auth in the fresh home comes from the env token (`COPILOT_GITHUB_TOKEN`;
  `ANTHROPIC_API_KEY`) the workflow already sets. Local plugin runs must have that
  token in the environment.

### 4.5 Config schema (`config.yaml`)
`plugins` is a flat list; each entry toggles independently.

```yaml
plugins:
  - source: marketplace
    enabled: true                       # default true when omitted
    repo: "github/awesome-copilot"      # owner/repo or git URL
    commit: "a1b2c3d4..."               # pinned commit (required for marketplace)
    plugins: ["frontend-web-dev"]       # plugin name(s) to install
  - source: local
    enabled: false                      # kept in file, parked
    path: "plugins/my-local-plugin"     # under instructions/<sanitized-repo>/
    plugins: ["my-local-plugin"]
```

Only `enabled: true` entries are installed. `enabled` defaults to `true`.

### 4.6 Wiring into the runners
```python
plugin_records, plugin_env = setup_plugins_from_config(config, entry, repo_path, agent_type, cli_cmd)
...
env = {**os.environ, ...existing..., **plugin_env}   # adds COPILOT_HOME / CLAUDE_CONFIG_DIR
result = subprocess.run(cmd_args, cwd=str(repo_path), env=env, ...)   # unchanged args
...
experiment_config = ExperimentConfiguration(
    ..., plugins=plugin_records or None,
)
```

### 4.7 Recording (`types.py`)
Mirror the existing `mcp_servers: list[str]` — no new field type.

```python
class ExperimentConfiguration(BaseModel):
    ...
    plugins: list[str] | None = None     # e.g. ["frontend-web-dev@a1b2c3d4", "my-local-plugin@local"]

    def is_empty(self) -> bool:
        return ( ... and self.plugins is None )
```
`"<name>@<commit>"` (marketplace) / `"<name>@local"` (local) keeps runs auditable.

### 4.8 AL-LSP
Untouched (`build_al_lsp_plugin`, `--al-lsp`, its `--plugin-dir`). Only the new
plugins feature uses the commands; the `local` source could express AL-LSP later.

## 5. Testing
Mirror `test_mcp_config.py` / `test_custom_instructions.py` (subprocess + git mocked):
- `tests/test_plugin_operations.py`: per-entry `enabled` (default true, disabled
  skipped → returns `([], {})`); marketplace clone/checkout; local copy into
  `.bcbench`; marketplace-name read from `marketplace.json`; the per-entry config
  home is created and passed as `env` to every `marketplace add` / `install` call
  (`COPILOT_HOME` for Copilot, `CLAUDE_CONFIG_DIR` for Claude); returned
  `(plugin_records, env_overrides)`; clean-before `rmtree` of `.bcbench/plugins` +
  home; `AgentError` on failure (partial home removed).
- Extend `test_experiment_configuration.py`: new `plugins` field + `is_empty`.
- Runner tests: assert `plugin_env` is merged into the agent-launch `env` and that
  `config.plugins` is recorded.
- Update mock `ExperimentConfiguration` scenarios
  (`commands/evaluate.py` `MockEvaluationPipeline`, result-serialization tests).

## 6. Documentation
- `EXPERIMENT.md`: add a `plugins` row + short schema/pinning note, and the
  env-token requirement for local plugin runs.
- `config.yaml`: document the `plugins` block in comments.

## 7. Open questions / verification (small, non-blocking)
1. Confirm the fresh-`CLAUDE_CONFIG_DIR` headless **session** loads the plugin and
   runs with `ANTHROPIC_API_KEY` (Copilot's fresh-`COPILOT_HOME` session is
   verified; Claude's install-into-fresh-dir + isolation is verified — only the
   authenticated session remains, and CI already runs Claude headless with the env
   key).
2. Ensure Copilot's `--log-dir=<output_dir>` still lands `process-*.log` in
   `output_dir` when `COPILOT_HOME` is redirected (used for turn-count metrics).
   `--log-dir` is explicit, so this should hold; verify during implementation.
3. Ordering vs `setup_instructions_from_config`: run plugin setup after it.
4. Migrate AL-LSP to a `local` plugin entry (deferred).
5. Optional agent-selection knob in a `plugins` entry (deferred; `--agent` covers it).

## 8. References (verified)
- Independent investigation: gist `alexey-pelykh/566a4e5160b305db703d543312a1e686`
  — `extraKnownMarketplaces`/`enabledPlugins` are trust-dialog-gated and ignored in
  headless mode; recommends explicit `plugin marketplace add` / `install` commands.
- Live probes: full Copilot plugin lifecycle against a local marketplace
  (non-interactive, offline, exit 0, "Installed 1 skill"); a real `copilot -p`
  session did **not** auto-install from repo-local settings; **fresh `COPILOT_HOME`
  headless session runs (exit 0) and loads an installed plugin's skill, isolated
  from the real config**; fresh `CLAUDE_CONFIG_DIR` isolates install the same way.
- Concurrency: `copilot-evaluation.yml` matrix `max-parallel: 64` on self-hosted
  `GitHub-BCBench`; `types.py.runner` per-category runner labels.
- PR #651 / commit `7eab2f9` (Haoran) — `agent/shared/plugin.py`.
- `agent/copilot/agent.py`, `agent/claude/agent.py` — runner + `shutil.which` CLI
  resolution + subprocess pattern to reuse.
- `types.py` — `ExperimentConfiguration`, `AgentType`.
