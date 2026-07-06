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

Both CLIs install at **user scope** (project scope is likewise ignored headless),
so both get the same **small, targeted** post-run teardown (`plugin uninstall` +
`marketplace remove`, verified reversible). Cloned content lives under `.bcbench`
(removed by the existing PR #651 cleanup). Installed plugins are recorded in
`ExperimentConfiguration`.

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
- Agent launch, model, MCP, permissions, auth are unaffected: the agent command
  line is unchanged; the plugin is simply installed into the CLI beforehand.

## 3. Goals / Non-goals

### Guiding principle
Keep it simple and reuse existing architecture. Use the CLIs' documented commands
rather than reverse-engineering config or fighting the headless trust gate. Keep
cloned content repo-local under `.bcbench`. The teardown is minimal, symmetric
with setup, uses documented commands, and is scoped to exactly what we installed.

### Goals
- Config-driven, per-entry enable/disable, multiple plugins at once.
- Marketplace plugins pinned to a git commit (reproducible); local plugins too.
- Plugins installed by name via the CLI's real commands, on Copilot and Claude.
- No config-home redirection; residue removed by a targeted post-run cleanup.
- Installed plugins recorded in `ExperimentConfiguration`.

### Non-goals
- Changing/migrating the AL-LSP plugin (left as-is).
- Selecting which plugin agent *drives* the run (existing `--agent` covers it).
- Relying on `extraKnownMarketplaces`/`enabledPlugins` injection (ignored headless).
- Redirecting `COPILOT_HOME` / `CLAUDE_CONFIG_DIR`; hand-writing CLI storage files.
- Dataset, category, or scoring changes.

## 4. Design

### 4.1 Flow (mirrors the existing setup_* functions)
New `operations/plugin_operations.py`:

```python
class InstalledPlugin(NamedTuple):
    plugin: str          # "frontend-web-dev"
    marketplace: str     # "awesome-copilot"
    record: str          # "frontend-web-dev@a1b2c3d4"  (for ExperimentConfiguration)

def setup_plugins_from_config(
    agent_config: dict, entry: BaseDatasetEntry, repo_path: Path,
    agent_type: AgentType, cli_cmd: str,
) -> list[InstalledPlugin]: ...

def teardown_plugins(cli_cmd: str, installed: list[InstalledPlugin]) -> None: ...
```

`setup_plugins_from_config` clones/copies enabled plugins under `.bcbench`, runs
`marketplace add` + `install` (user scope), and returns what it installed (for the
result record and teardown). The agent launch command is unchanged.

### 4.2 Materialize content into `.bcbench/`
- **Clean before / self-heal:** `remove_agent_plugin` for stale folders, and
  defensively `uninstall` / `marketplace remove` our names (in case a prior run
  crashed before teardown).
- **marketplace** (`repo` + `commit`): shallow-clone into
  `<repo>/.bcbench/plugins/<marketplace-name>` and `git checkout <commit>` (small
  reused git helper). Read the marketplace `name` from its `marketplace.json`.
- **local** (`path`): copy into `<repo>/.bcbench/plugins/<name>`. `path` resolves
  under `src/bcbench/agent/shared/instructions/<sanitized-repo>/`.
- Failures raise `AgentError`.

### 4.3 Install via the CLI commands (user scope, both CLIs)
For each enabled entry, using the resolved CLI binary:
- `<cli> plugin marketplace add <repo>/.bcbench/plugins/<marketplace-name>`
- `<cli> plugin install <plugin>@<marketplace-name>` for each requested plugin
- Verify with `<cli> plugin list`; failures raise `AgentError`.

### 4.4 Teardown (symmetric, both CLIs)
In a `finally` around the agent run, for each installed plugin:
- `<cli> plugin uninstall <plugin>` then `<cli> plugin marketplace remove <marketplace>`
  (verified reversible; best-effort, logged, never masks the run outcome).
- `.bcbench` cloned content is removed by `remove_agent_plugin` / `git clean -fd`.
- The developer's real global config is returned to baseline.

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
installed = setup_plugins_from_config(config, entry, repo_path, agent_type, cli_cmd)
try:
    result = subprocess.run(cmd_args, cwd=str(repo_path), ...)   # unchanged agent launch
    ...
finally:
    teardown_plugins(cli_cmd, installed)

experiment_config = ExperimentConfiguration(
    ..., plugins=[p.record for p in installed] or None,
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
  skipped); marketplace clone/checkout; local copy into `.bcbench`; marketplace-name
  read from `marketplace.json`; command construction for `marketplace add` /
  `install` (user scope, both CLIs); `InstalledPlugin` records; `teardown_plugins`
  builds correct `uninstall` / `marketplace remove`; clean-before self-heal;
  `AgentError` on failure.
- Extend `test_experiment_configuration.py`: new `plugins` field + `is_empty`.
- Update mock `ExperimentConfiguration` scenarios
  (`commands/evaluate.py` `MockEvaluationPipeline`, result-serialization tests).

## 6. Documentation
- `EXPERIMENT.md`: add a `plugins` row + short schema/pinning note.
- `config.yaml`: document the `plugins` block in comments.

## 7. Open questions / verification (small, non-blocking)
1. Confirm the Claude lifecycle (`marketplace add` + `install` + `uninstall` +
   `marketplace remove`, user scope) end-to-end, mirroring the verified Copilot
   lifecycle. High confidence; verify during implementation.
2. Ordering vs `setup_instructions_from_config`: run plugin setup after it. Low
   risk (global config, not repo files), but keep the order explicit.
3. Migrate AL-LSP to a `local` plugin entry (deferred).
4. Optional agent-selection knob in a `plugins` entry (deferred; `--agent` covers it).

## 8. References (verified)
- Independent investigation: gist `alexey-pelykh/566a4e5160b305db703d543312a1e686`
  — `extraKnownMarketplaces`/`enabledPlugins` are trust-dialog-gated and ignored in
  headless mode; recommends explicit `plugin marketplace add` / `install` commands.
- Live probes: full Copilot plugin lifecycle against a local marketplace
  (non-interactive, offline, exit 0, "Installed 1 skill", baseline restored); a real
  `copilot -p` session did **not** auto-install from repo-local settings.
- PR #651 / commit `7eab2f9` (Haoran) — `agent/shared/plugin.py`.
- `agent/copilot/agent.py`, `agent/claude/agent.py` — runner + `shutil.which` CLI
  resolution + subprocess pattern to reuse.
- `types.py` — `ExperimentConfiguration`, `AgentType`.
