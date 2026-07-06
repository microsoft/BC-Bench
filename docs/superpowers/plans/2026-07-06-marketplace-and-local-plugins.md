# Marketplace & Local Plugins Experiment Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a config-driven experiment toggle that installs agent plugins (marketplace-pinned-to-commit or local) into the running CLI via its own `plugin marketplace add` + `plugin install` commands, records them in results, and keeps concurrent entries isolated.

**Architecture:** A new `operations/plugin_operations.py` reads a `plugins` list from `agent/shared/config.yaml`, clones each marketplace at its pinned commit into `<repo>/.bcbench/plugins/`, and installs the requested plugins by name via the CLI commands into a **fresh per-entry config home** (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under `<repo>/.bcbench/`). It returns `(plugin_records, env_overrides)`: the records fold into `ExperimentConfiguration`, and `env_overrides` is merged into the agent-launch environment so the agent runs against the same isolated home. The per-entry home means concurrent matrix entries never share the user-scope plugin store — so there is **no teardown** (the home is discarded with the checkout; a clean-before removes any stale one). Config injection (`extraKnownMarketplaces`) is NOT used — it is trust-dialog-gated and ignored in headless mode.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, `subprocess` for `git` + the agent CLIs, pytest with `unittest.mock`, `uv` for running commands.

## Global Constraints

- Python `>=3.13`; strong typing / type hints required (ruff `ANN`).
- Run everything through `uv` (e.g. `uv run pytest ...`, `uv run ruff ...`).
- Use the module logger (`get_logger(__name__)`); never `print` in `src/bcbench`.
- Line length 200; ruff rules per `pyproject.toml`. `subprocess.run` MUST pass an explicit `check=` (ruff `PLW1510`).
- No new domain model types for recording — `ExperimentConfiguration.plugins` is `list[str] | None`, mirroring `mcp_servers`.
- Marketplace/local source content must be a **marketplace root** (a directory containing `.claude-plugin/marketplace.json` or `.github/plugin/marketplace.json`).
- `operations/plugin_operations.py` must NOT import from `bcbench.agent.*` (would create a cycle: `bcbench.agent.__init__` imports the runners, which import `bcbench.operations`).
- Do NOT modify the AL-LSP plugin mechanism (`build_al_lsp_plugin`, `--al-lsp`, `--plugin-dir`).
- Commit after every task (frequent commits).

---

### Task 1: Add `plugins` field to `ExperimentConfiguration`

**Files:**
- Modify: `src/bcbench/types.py` (class `ExperimentConfiguration`, ~lines 74-104)
- Test: `tests/test_experiment_configuration.py`

**Interfaces:**
- Produces: `ExperimentConfiguration(plugins: list[str] | None = None)`; `is_empty()` returns True only when `plugins is None` along with the existing fields.

- [ ] **Step 1: Write the failing tests**

Add these methods to class `TestExperimentConfiguration` in `tests/test_experiment_configuration.py`:

```python
    def test_default_plugins_is_none(self):
        config = ExperimentConfiguration()

        assert config.plugins is None
        assert config.is_empty()

    def test_with_plugins(self):
        plugins = ["frontend-web-dev@a1b2c3d4", "my-local-plugin@local"]
        config = ExperimentConfiguration(plugins=plugins)

        assert config.plugins == plugins
        assert not config.is_empty()

    def test_empty_plugins_list_is_not_empty_config(self):
        config = ExperimentConfiguration(plugins=[])

        assert config.plugins == []
        assert not config.is_empty()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_experiment_configuration.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'plugins'` (and `test_default_plugins_is_none` fails on `config.plugins`).

- [ ] **Step 3: Add the field and update `is_empty`**

In `src/bcbench/types.py`, inside `class ExperimentConfiguration`, add the field after `custom_agent`:

```python
    # Custom agent name used in experiment (if any)
    custom_agent: str | None = None

    # Plugins installed for this experiment: "<name>@<commit>" (marketplace) or "<name>@local"
    plugins: list[str] | None = None
```

Then extend `is_empty`:

```python
    def is_empty(self) -> bool:
        """Check if this configuration has all default/empty values.

        An empty configuration means no special experiment settings were used.
        This is useful for comparing with None (no experiment) vs default experiment.
        """
        return self.mcp_servers is None and self.al_lsp_enabled is False and self.custom_instructions is False and self.skills_enabled is False and self.custom_agent is None and self.plugins is None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_experiment_configuration.py -v`
Expected: PASS (all tests, including the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/types.py tests/test_experiment_configuration.py
git commit -m "feat: record installed plugins in ExperimentConfiguration"
```

---

### Task 2: Add `clone_at_commit` git helper

**Files:**
- Modify: `src/bcbench/operations/git_operations.py`
- Modify: `src/bcbench/operations/__init__.py` (export)
- Test: `tests/test_git_operations.py`

**Interfaces:**
- Produces: `clone_at_commit(repo: str, commit: str, dest: Path) -> None` — clones `repo` (a `owner/repo` slug or a full git URL) at `commit` into `dest` (created if missing), shallowly.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_git_operations.py` (create the file if it does not exist, with the import block shown):

```python
from pathlib import Path
from unittest.mock import patch

from bcbench.operations.git_operations import clone_at_commit


@patch("bcbench.operations.git_operations.subprocess.run")
def test_clone_at_commit_owner_repo_builds_https_url(mock_run, tmp_path):
    dest = tmp_path / "clone"

    clone_at_commit("github/awesome-copilot", "a" * 40, dest)

    assert dest.is_dir()
    commands = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "init", "-q"] in commands
    assert ["git", "remote", "add", "origin", "https://github.com/github/awesome-copilot.git"] in commands
    assert ["git", "fetch", "--depth", "1", "origin", "a" * 40] in commands
    assert ["git", "checkout", "-q", "FETCH_HEAD"] in commands


@patch("bcbench.operations.git_operations.subprocess.run")
def test_clone_at_commit_full_url_used_verbatim(mock_run, tmp_path):
    clone_at_commit("https://gitlab.com/o/r.git", "b" * 40, tmp_path / "c")

    remote_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][:3] == ["git", "remote", "add"]]
    assert remote_calls == [["git", "remote", "add", "origin", "https://gitlab.com/o/r.git"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_git_operations.py -k clone_at_commit -v`
Expected: FAIL — `ImportError: cannot import name 'clone_at_commit'`.

- [ ] **Step 3: Implement `clone_at_commit`**

Append to `src/bcbench/operations/git_operations.py`:

```python
def clone_at_commit(repo: str, commit: str, dest: Path) -> None:
    """Shallow-clone `repo` at a specific `commit` into `dest`.

    Args:
        repo: A GitHub `owner/repo` slug or a full git URL (`https://...` or `...git`).
        commit: The 40-char commit SHA to check out (GitHub allows fetching a SHA directly).
        dest: Target directory (created if missing).
    """
    url = repo if ("://" in repo or repo.endswith(".git")) else f"https://github.com/{repo}.git"
    logger.info(f"Cloning {url} @ {commit} into {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "fetch", "--depth", "1", "origin", commit], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info(f"Cloned {url} @ {commit}")
```

In `src/bcbench/operations/__init__.py`, add `clone_at_commit` to the `git_operations` import block and to `__all__` (keep both alphabetized):

```python
from bcbench.operations.git_operations import (
    apply_patch,
    checkout_commit,
    clean_project_paths,
    clean_repo,
    clone_at_commit,
    commit_changes,
    stage_and_get_diff,
)
```

```python
    "checkout_commit",
    "clean_project_paths",
    "clean_repo",
    "clone_at_commit",
    "commit_changes",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_git_operations.py -k clone_at_commit -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/operations/git_operations.py src/bcbench/operations/__init__.py tests/test_git_operations.py
git commit -m "feat: add clone_at_commit git helper for pinned marketplace clones"
```

---

### Task 3: `plugin_operations.py` — materialize + marketplace-name helpers

**Files:**
- Create: `src/bcbench/operations/plugin_operations.py`
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Produces:
  - `_read_marketplace_name(marketplace_dir: Path) -> str` — reads `name` from `.claude-plugin/marketplace.json` or `.github/plugin/marketplace.json`.
  - `_materialize(entry_cfg: dict, entry: BaseDatasetEntry, plugins_root: Path) -> tuple[Path, str]` — clones (marketplace) or copies (local) into `plugins_root`, returns `(marketplace_dir, record_suffix)` where `record_suffix` is the commit (marketplace) or the literal `"local"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plugin_operations.py`:

```python
import json
from pathlib import Path

import pytest

from bcbench.exceptions import AgentError
from bcbench.operations import plugin_operations as po
from tests.conftest import create_dataset_entry


def _make_marketplace(root: Path, manifest_rel: str = ".claude-plugin/marketplace.json", name: str = "probe-mp") -> Path:
    """Create a minimal marketplace directory and return its root."""
    manifest = root / manifest_rel
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": name, "plugins": [{"name": "probe-plugin", "source": "./probe-plugin"}]}), encoding="utf-8")
    plugin_json = root / "probe-plugin" / ".claude-plugin" / "plugin.json"
    plugin_json.parent.mkdir(parents=True, exist_ok=True)
    plugin_json.write_text(json.dumps({"name": "probe-plugin", "version": "0.0.1"}), encoding="utf-8")
    return root


def test_read_marketplace_name_claude_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".claude-plugin/marketplace.json", name="my-mp")
    assert po._read_marketplace_name(tmp_path) == "my-mp"


def test_read_marketplace_name_github_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".github/plugin/marketplace.json", name="gh-mp")
    assert po._read_marketplace_name(tmp_path) == "gh-mp"


def test_read_marketplace_name_missing_raises(tmp_path):
    with pytest.raises(AgentError, match="marketplace.json"):
        po._read_marketplace_name(tmp_path)


def test_materialize_marketplace_clones_at_commit(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()

    def fake_clone(repo: str, commit: str, dest: Path) -> None:
        _make_marketplace(dest, name="cloned-mp")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    entry = create_dataset_entry()
    entry_cfg = {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "a" * 40


def test_materialize_local_copies_from_instructions(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()
    source_root = tmp_path / "instructions"
    _make_marketplace(source_root / "plugins" / "my-mp", name="local-mp")

    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: source_root)
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/my-mp", "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "local"


def test_materialize_local_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: tmp_path / "nope")
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/absent", "plugins": ["x"]}

    with pytest.raises(AgentError, match="Local plugin marketplace not found"):
        po._materialize(entry_cfg, entry, tmp_path / "plugins_root")


def test_materialize_unknown_source_raises(tmp_path):
    entry = create_dataset_entry()
    with pytest.raises(AgentError, match="Unknown plugin source"):
        po._materialize({"source": "bogus", "plugins": []}, entry, tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugin_operations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bcbench.operations.plugin_operations'`.

- [ ] **Step 3: Create `plugin_operations.py` with the helpers**

Create `src/bcbench/operations/plugin_operations.py`:

```python
"""Install agent plugins (marketplace or local) declared in config, via the CLI's plugin commands.

Config injection (`extraKnownMarketplaces` / `enabledPlugins`) is trust-dialog-gated and ignored in
headless mode, so we drive the CLI's real `plugin marketplace add` + `plugin install` commands.
Because the plugin store is user-scope/global and execution-based categories run entries as a
parallel matrix on a shared self-hosted runner, each entry installs into a fresh per-entry config
home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR`) under `<repo>/.bcbench/`, which the runner also applies
to the agent launch. Marketplace content is cloned at its pinned commit into `<repo>/.bcbench/plugins/`.

NOTE: do NOT import from `bcbench.agent.*` here — `bcbench.agent.__init__` imports the runners,
which import `bcbench.operations`; importing agent from operations would create a cycle.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations.git_operations import clone_at_commit
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentType

logger = get_logger(__name__)

_BCBENCH_ROOT = ".bcbench"
_PLUGINS_FOLDER = "plugins"  # under <repo>/.bcbench/plugins/
_MARKETPLACE_MANIFESTS = (".claude-plugin/marketplace.json", ".github/plugin/marketplace.json")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-")


def _read_marketplace_name(marketplace_dir: Path) -> str:
    for rel in _MARKETPLACE_MANIFESTS:
        manifest = marketplace_dir / rel
        if manifest.is_file():
            name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
            if name:
                return name
    raise AgentError(f"No marketplace.json with a 'name' found under {marketplace_dir}")


def _materialize(entry_cfg: dict, entry: BaseDatasetEntry, plugins_root: Path) -> tuple[Path, str]:
    """Clone (marketplace) or copy (local) the marketplace into plugins_root.

    Returns:
        (marketplace_dir, record_suffix) where record_suffix is the pinned commit or "local".
    """
    source = entry_cfg["source"]
    match source:
        case "marketplace":
            repo: str = entry_cfg["repo"]
            commit: str = entry_cfg["commit"]
            dest = plugins_root / _slug(repo)
            clone_at_commit(repo, commit, dest)
            return dest, commit
        case "local":
            rel_path: str = entry_cfg["path"]
            src = _get_source_instructions_path(entry.repo) / rel_path
            if not src.is_dir():
                raise AgentError(f"Local plugin marketplace not found: {src}")
            dest = plugins_root / _slug(rel_path)
            if dest.exists():
                rmtree(dest)
            copytree(src, dest)
            return dest, "local"
        case _:
            raise AgentError(f"Unknown plugin source: {source!r}")
```

(`os` and `subprocess` are used by the setup function added in Task 4.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_operations.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/operations/plugin_operations.py tests/test_plugin_operations.py
git commit -m "feat: add plugin materialize + marketplace-name helpers"
```

---

### Task 4: `plugin_operations.py` — install into a per-entry isolated home

**Files:**
- Modify: `src/bcbench/operations/plugin_operations.py`
- Modify: `src/bcbench/operations/__init__.py` (export)
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `_materialize`, `_read_marketplace_name` (Task 3); `AgentType`.
- Produces:
  - `setup_plugins_from_config(agent_config: dict, entry: BaseDatasetEntry, repo_path: Path, agent_type: AgentType, cli_cmd: str) -> tuple[list[str], dict[str, str]]` — returns `(plugin_records, env_overrides)`; `env_overrides` is `{"COPILOT_HOME": <dir>}` / `{"CLAUDE_CONFIG_DIR": <dir>}` (or `{}` when nothing is enabled) that the runner must merge into the agent-launch env.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin_operations.py`:

```python
from bcbench.types import AgentType


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs.get("env")))

        class _R:
            returncode = 0

        return _R()


def _marketplace_entry_cfg():
    return {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}


def test_setup_no_plugins_returns_empty(tmp_path):
    records, env = po.setup_plugins_from_config({}, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert records == []
    assert env == {}


def test_setup_disabled_entry_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(po.subprocess, "run", _Recorder())
    cfg = {"plugins": [{**_marketplace_entry_cfg(), "enabled": False}]}
    records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert records == []
    assert env == {}


def test_setup_installs_into_isolated_home_and_records(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    rec = _Recorder()
    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    monkeypatch.setattr(po.subprocess, "run", rec)

    cfg = {"plugins": [_marketplace_entry_cfg()]}
    records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")

    home = str(tmp_path / ".bcbench" / "copilot-home")
    assert records == ["probe-plugin@" + "a" * 40]
    assert env == {"COPILOT_HOME": home}

    add_call = next(c for c in rec.calls if c[0][:4] == ["copilot", "plugin", "marketplace", "add"])
    install_call = next(c for c in rec.calls if c[0][:3] == ["copilot", "plugin", "install"])
    assert add_call[0][4] == str(tmp_path / ".bcbench" / "plugins" / "github-awesome-copilot")
    assert install_call[0] == ["copilot", "plugin", "install", "probe-plugin@awesome-copilot"]
    # commands ran with the isolated home in their env
    assert add_call[1]["COPILOT_HOME"] == home
    assert install_call[1]["COPILOT_HOME"] == home


def test_setup_claude_uses_claude_config_dir(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    monkeypatch.setattr(po.subprocess, "run", _Recorder())
    cfg = {"plugins": [_marketplace_entry_cfg()]}

    _records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.CLAUDE, "claude")

    assert env == {"CLAUDE_CONFIG_DIR": str(tmp_path / ".bcbench" / "claude-home")}


def test_setup_failure_removes_partial_home_and_raises(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)

    def failing_run(args, **kwargs):
        raise po.subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(po.subprocess, "run", failing_run)
    cfg = {"plugins": [_marketplace_entry_cfg()]}

    with pytest.raises(AgentError, match="Plugin setup failed"):
        po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")

    assert not (tmp_path / ".bcbench" / "copilot-home").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugin_operations.py -k "setup" -v`
Expected: FAIL — `AttributeError: module 'bcbench.operations.plugin_operations' has no attribute 'setup_plugins_from_config'`.

- [ ] **Step 3: Implement `setup_plugins_from_config`**

Append to `src/bcbench/operations/plugin_operations.py`:

```python
def _home_env_var(agent_type: AgentType) -> str:
    match agent_type:
        case AgentType.COPILOT:
            return "COPILOT_HOME"
        case AgentType.CLAUDE:
            return "CLAUDE_CONFIG_DIR"
        case _:
            raise AgentError(f"Unsupported agent type for plugins: {agent_type}")


def _run_plugin_cmd(cli_cmd: str, args: list[str], env: dict[str, str]) -> None:
    subprocess.run([cli_cmd, "plugin", *args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def setup_plugins_from_config(agent_config: dict, entry: BaseDatasetEntry, repo_path: Path, agent_type: AgentType, cli_cmd: str) -> tuple[list[str], dict[str, str]]:
    """Install every enabled plugin entry into a fresh per-entry CLI config home.

    Returns (plugin_records, env_overrides). env_overrides sets the isolated config home
    (COPILOT_HOME / CLAUDE_CONFIG_DIR) that the runner must also apply to the agent launch, so
    concurrent matrix entries never share the user-scope plugin store. Returns ([], {}) when no
    entry is enabled. Raises AgentError on failure (after removing the partial home).
    """
    entries = [e for e in (agent_config.get("plugins") or []) if e.get("enabled", True)]
    if not entries:
        return [], {}

    bcbench_dir = repo_path / _BCBENCH_ROOT
    plugins_root = bcbench_dir / _PLUGINS_FOLDER
    home = bcbench_dir / f"{agent_type.value}-home"
    for path in (plugins_root, home):
        if path.exists():
            rmtree(path)  # clean-before
        path.mkdir(parents=True, exist_ok=True)

    home_var = _home_env_var(agent_type)
    env = {**os.environ, home_var: str(home)}
    records: list[str] = []
    try:
        for entry_cfg in entries:
            marketplace_dir, record_suffix = _materialize(entry_cfg, entry, plugins_root)
            marketplace_name = _read_marketplace_name(marketplace_dir)
            _run_plugin_cmd(cli_cmd, ["marketplace", "add", str(marketplace_dir)], env)
            for plugin in entry_cfg["plugins"]:
                _run_plugin_cmd(cli_cmd, ["install", f"{plugin}@{marketplace_name}"], env)
                records.append(f"{plugin}@{record_suffix}")
                logger.info(f"Installed plugin {plugin}@{marketplace_name} into {home}")
    except (subprocess.CalledProcessError, OSError) as e:
        if home.exists():
            rmtree(home)
        raise AgentError(f"Plugin setup failed: {e}") from e

    return records, {home_var: str(home)}
```

In `src/bcbench/operations/__init__.py`, add the import and `__all__` entry (keep alphabetized within the block):

```python
from bcbench.operations.plugin_operations import setup_plugins_from_config
```

```python
    "setup_hooks",
    "setup_instructions_from_config",
    "setup_plugins_from_config",
    "setup_repo_prebuild",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_operations.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/operations/plugin_operations.py src/bcbench/operations/__init__.py tests/test_plugin_operations.py
git commit -m "feat: install plugins into a per-entry isolated CLI config home"
```

---

### Task 5: Wire plugin setup into the Copilot runner

**Files:**
- Modify: `src/bcbench/agent/copilot/agent.py`
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `setup_plugins_from_config` (Task 4); `ExperimentConfiguration.plugins` (Task 1).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_operations.py`:

```python
from unittest.mock import MagicMock, patch

from bcbench.dataset import BaseDatasetEntry


@patch("bcbench.agent.copilot.agent.setup_plugins_from_config")
@patch("bcbench.agent.copilot.agent.parse_tool_usage_from_hooks", return_value=None)
@patch("bcbench.agent.copilot.agent.parse_metrics", return_value=None)
@patch("bcbench.agent.copilot.agent.setup_hooks")
@patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None)
@patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False)
@patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False)
@patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None)
@patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None))
@patch("bcbench.agent.copilot.agent.build_prompt", return_value="do the task")
@patch("bcbench.agent.copilot.agent.shutil.which", return_value="copilot")
@patch("bcbench.agent.copilot.agent.subprocess.run")
def test_copilot_runner_records_plugins_and_sets_home(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, tmp_path
):
    from bcbench.agent.copilot.agent import run_copilot_agent
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stderr=b"")
    home = str(tmp_path / ".bcbench" / "copilot-home")
    mock_setup.return_value = (["frontend-web-dev@a1b2c3d4"], {"COPILOT_HOME": home})
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_copilot_agent(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    _args, kwargs = mock_run.call_args
    assert kwargs["env"]["COPILOT_HOME"] == home
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_operations.py -k copilot_runner -v`
Expected: FAIL — `setup_plugins_from_config` not imported/wired in `bcbench.agent.copilot.agent`, or `config.plugins is None`.

- [ ] **Step 3: Wire the runner**

In `src/bcbench/agent/copilot/agent.py`, update the operations import line to include the new function:

```python
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config, setup_plugins_from_config
```

Resolve the CLI binary **before** the plugin setup and reuse it. Replace the existing block that computes `config` / finds `copilot_cmd` so it reads:

```python
    tool_log_path: Path = setup_hooks(repo_path, AgentType.COPILOT, output_dir)

    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes PowerShell,
    # which re-parses arguments and corrupts prompts containing double quotes (e.g. JSON examples).
    copilot_cmd = shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    plugin_records, plugin_env = setup_plugins_from_config(copilot_config, entry, repo_path, AgentType.COPILOT, copilot_cmd)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=plugin_records or None,
    )

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")
```

Then delete the now-duplicate `copilot_cmd = shutil.which(...)` / `if not copilot_cmd: raise AgentError(...)` block that currently sits just before the `try:` (it has moved up).

Merge `plugin_env` into the agent-launch environment. In the `subprocess.run(...)` call, change the `env=` dict to include `**plugin_env`:

```python
            env={
                **os.environ,
                "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "true",
                "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true",
                **plugin_env,
            },
```

(No `finally`/teardown — the per-entry home is discarded with the checkout; `setup_plugins_from_config` clean-befores any stale home.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugin_operations.py -k copilot_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/agent/copilot/agent.py tests/test_plugin_operations.py
git commit -m "feat: install plugins into a per-entry home in the Copilot runner"
```

---

### Task 6: Wire plugin setup into the Claude runner

**Files:**
- Modify: `src/bcbench/agent/claude/agent.py`
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `setup_plugins_from_config`; `ExperimentConfiguration.plugins`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_operations.py`:

```python
@patch("bcbench.agent.claude.agent.setup_plugins_from_config")
@patch("bcbench.agent.claude.agent.parse_tool_usage_from_hooks", return_value=None)
@patch("bcbench.agent.claude.agent.parse_metrics", return_value=None)
@patch("bcbench.agent.claude.agent.setup_hooks")
@patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None)
@patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False)
@patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False)
@patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None)
@patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None))
@patch("bcbench.agent.claude.agent.build_prompt", return_value="do the task")
@patch("bcbench.agent.claude.agent.shutil.which", return_value="claude")
@patch("bcbench.agent.claude.agent.subprocess.run")
def test_claude_runner_records_plugins_and_sets_config_dir(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, tmp_path
):
    from bcbench.agent.claude.agent import run_claude_code
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stdout=b'{"result": "ok"}')
    cfg_dir = str(tmp_path / ".bcbench" / "claude-home")
    mock_setup.return_value = (["frontend-web-dev@a1b2c3d4"], {"CLAUDE_CONFIG_DIR": cfg_dir})
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_claude_code(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    _args, kwargs = mock_run.call_args
    assert kwargs["env"]["CLAUDE_CONFIG_DIR"] == cfg_dir
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_operations.py -k claude_runner -v`
Expected: FAIL — `setup_plugins_from_config` not wired in `bcbench.agent.claude.agent`, or the `subprocess.run` call has no `env` kwarg (`KeyError: 'env'`).

- [ ] **Step 3: Wire the runner**

In `src/bcbench/agent/claude/agent.py`, update the operations import:

```python
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config, setup_plugins_from_config
```

Resolve the CLI binary before plugin setup and reuse it. Replace the block that builds `config` and finds `claude_cmd` so it reads:

```python
    tool_log_path: Path = setup_hooks(repo_path, AgentType.CLAUDE, output_dir)

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

    plugin_records, plugin_env = setup_plugins_from_config(claude_config, entry, repo_path, AgentType.CLAUDE, claude_cmd)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=plugin_records or None,
    )

    logger.info(f"Executing Claude Code in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")
```

Then delete the now-duplicate `claude_cmd = shutil.which("claude")` / `if not claude_cmd: raise AgentError(...)` block that currently sits just before the `try:`.

The Claude `subprocess.run(...)` call currently passes no `env`. Add one that carries the isolated home:

```python
        result = subprocess.run(
            cmd_args,
            cwd=str(repo_path),
            env={**os.environ, **plugin_env},
            timeout=_config.timeout.agent_execution,
            check=True,
            capture_output=True,
        )
```

Ensure `import os` is present at the top of `src/bcbench/agent/claude/agent.py` (add it if missing).

(No `finally`/teardown.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugin_operations.py -k claude_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/agent/claude/agent.py tests/test_plugin_operations.py
git commit -m "feat: install plugins into a per-entry home in the Claude runner"
```

---

### Task 7: Config schema, docs, mock scenario, and full verification

**Files:**
- Modify: `src/bcbench/agent/shared/config.yaml`
- Modify: `EXPERIMENT.md`
- Modify: `src/bcbench/commands/evaluate.py` (`MockEvaluationPipeline` scenarios)
- Test: full suite + lint

**Interfaces:**
- Consumes: everything above. No new public interface.

- [ ] **Step 1: Add the `plugins` block to `config.yaml`**

In `src/bcbench/agent/shared/config.yaml`, add this block after the `agents:` block (before `mcp:`):

```yaml
# controls installing agent plugins (skills/agents/mcp/hooks bundles) into the CLI for the run.
# each enabled entry is installed via the CLI's `plugin marketplace add` + `plugin install` into a
# fresh per-entry config home (COPILOT_HOME / CLAUDE_CONFIG_DIR under <repo>/.bcbench/), so parallel
# matrix entries never share the user-scope plugin store and no teardown is needed.
# NOTE: config injection (extraKnownMarketplaces/enabledPlugins) is trust-dialog-gated and ignored
#       in headless mode, so we drive the real CLI commands instead.
# NOTE: a fresh home authenticates via the env token the workflow sets (COPILOT_GITHUB_TOKEN;
#       ANTHROPIC_API_KEY) — local plugin runs must have that token in the environment.
# source: "marketplace" (repo + commit) or "local" (path under instructions/<owner>-<repo>/,
#         which must be a marketplace root containing .claude-plugin/marketplace.json).
plugins: []
  # - source: marketplace
  #   enabled: true
  #   repo: "github/awesome-copilot"
  #   commit: "<40-char-commit-sha>"
  #   plugins: ["frontend-web-dev"]
  # - source: local
  #   enabled: false
  #   path: "plugins/my-local-plugin"
  #   plugins: ["my-local-plugin"]
```

- [ ] **Step 2: Document the toggle in `EXPERIMENT.md`**

In `EXPERIMENT.md`, add a row to the config table (after the `mcp.servers` row):

```markdown
| `plugins` | _(empty)_ | List of agent plugins to install for the run (marketplace pinned to a commit, or local). Each enabled entry is installed via the CLI's `plugin marketplace add` + `plugin install` into a per-entry isolated config home. |
```

And add this subsection after the "Custom instructions / skills / custom agents" subsection:

```markdown
### Marketplace & local plugins

`plugins` is a list; each entry is toggled by its own `enabled` (default `true`):

- `source: marketplace` — `repo` (`owner/repo` or git URL) + `commit` (pinned for reproducibility) + `plugins` (names to install).
- `source: local` — `path` (relative to `instructions/<owner>-<repo>/`, pointing at a marketplace root with `.claude-plugin/marketplace.json`) + `plugins`.

At runtime the marketplace is cloned at its commit into `<repo>/.bcbench/plugins/` and installed with the CLI's own commands into a fresh per-entry config home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under `.bcbench/`), which keeps parallel matrix entries isolated. A fresh home authenticates via the env token the workflow already sets (`COPILOT_GITHUB_TOKEN`; `ANTHROPIC_API_KEY`) — local plugin runs must have that token set. Installed plugins are recorded in the result's `ExperimentConfiguration.plugins` as `"<name>@<commit>"` / `"<name>@local"`.
```

- [ ] **Step 3: Add a plugins scenario to the mock pipeline**

In `src/bcbench/commands/evaluate.py`, in `MockEvaluationPipeline.run_agent`, extend the `experiment_config_scenarios` list to include a plugins example (add one element):

```python
        experiment_config_scenarios: list[ExperimentConfiguration | None] = [
            ExperimentConfiguration(mcp_servers=["magic-mcp"], custom_instructions=True, custom_agent="custom-agent-v1"),
            ExperimentConfiguration(mcp_servers=["magic-mcp"]),
            ExperimentConfiguration(custom_instructions=True),
            None,
            ExperimentConfiguration(),
            ExperimentConfiguration(custom_agent="custom-agent-v1"),
            ExperimentConfiguration(plugins=["frontend-web-dev@a1b2c3d4"]),
        ]
```

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -q`
Expected: PASS. If `tests/test_result_serialization.py` (or another snapshot test) fails because it compares a full `ExperimentConfiguration` dump and now sees the new `plugins` key, update the expected value in that test to include `"plugins": null` (or the recorded list) — do not remove the field.

- [ ] **Step 5: Lint / format**

Run: `uv run ruff check src/bcbench/operations/plugin_operations.py src/bcbench/operations/git_operations.py src/bcbench/agent/copilot/agent.py src/bcbench/agent/claude/agent.py src/bcbench/types.py tests/test_plugin_operations.py tests/test_git_operations.py`
Then: `uv run ruff format .`
Expected: no errors; formatter reports files unchanged or reformats cleanly.

- [ ] **Step 6: Commit**

```bash
git add src/bcbench/agent/shared/config.yaml EXPERIMENT.md src/bcbench/commands/evaluate.py tests/
git commit -m "docs+config: document plugins toggle, add config block and mock scenario"
```

---

## Notes for the implementer

- **Do not** load plugins via `extraKnownMarketplaces`/`enabledPlugins` injection — verified (and confirmed by gist `alexey-pelykh/566a4e5160b305db703d543312a1e686`) to be ignored in headless mode.
- **Concurrency is why the per-entry home exists.** `copilot-evaluation.yml` runs entries with `max-parallel: 64` on the shared self-hosted `GitHub-BCBench` runner; the CLI plugin store is user-scope/global, so without a per-entry home two entries would corrupt each other's installs. The isolated home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under `.bcbench/`) removes the race and any teardown.
- The full plugin lifecycle and per-entry-home isolation were verified live: fresh `COPILOT_HOME` accepts `marketplace add`/`install`, `copilot skill list` shows the installed plugin's skill, and a real `copilot -p` session runs (exit 0, auth via `COPILOT_GITHUB_TOKEN`, no onboarding block), leaving the real `~/.copilot` untouched; fresh `CLAUDE_CONFIG_DIR` isolates install the same way.
- `git fetch --depth 1 origin <sha>` works on GitHub (arbitrary SHA fetch allowed). A host that disallows it fails loudly as `AgentError` (fails the entry, like other setup failures).
- Setup ordering: `setup_plugins_from_config` runs after `setup_hooks` and the other `setup_*` — it does not touch `.github`/`.claude`.
- Copilot passes `--log-dir=<output_dir>` explicitly, so `process-*.log` (used for turn-count metrics) should still land in `output_dir` even with `COPILOT_HOME` redirected; confirm during Task 5.
