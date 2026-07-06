# Marketplace & Local Plugins Experiment Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a config-driven experiment toggle that installs agent plugins (marketplace-pinned-to-commit or local) into the running CLI via its own `plugin marketplace add` + `plugin install` commands, records them in results, and cleanly removes them afterward.

**Architecture:** A new `operations/plugin_operations.py` reads a `plugins` list from `agent/shared/config.yaml`, clones each marketplace at its pinned commit into `<repo>/.bcbench/plugins/`, installs the requested plugins by name via the CLI commands (user scope, both Copilot and Claude), and returns records folded into `ExperimentConfiguration`. A symmetric teardown (`uninstall` + `marketplace remove`) runs in a `finally` in each agent runner. `.bcbench` content is removed by `git clean` and an inline clean-before. Config injection (`extraKnownMarketplaces`) is NOT used — it is trust-dialog-gated and ignored in headless mode.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, `subprocess` for `git` + the agent CLIs, pytest with `unittest.mock`, `uv` for running commands.

## Global Constraints

- Python `>=3.13`; strong typing / type hints required (ruff `ANN`).
- Run everything through `uv` (e.g. `uv run pytest ...`, `uv run ruff ...`).
- Use the module logger (`get_logger(__name__)`); never `print` in `src/bcbench`.
- Line length 200; ruff rules per `pyproject.toml`. `subprocess.run` MUST pass an explicit `check=` (ruff `PLW1510`).
- No new domain model types for recording — `ExperimentConfiguration.plugins` is `list[str] | None`, mirroring `mcp_servers`.
- Marketplace/local source content must be a **marketplace root** (a directory containing `.claude-plugin/marketplace.json` or `.github/plugin/marketplace.json`).
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
from unittest.mock import call, patch

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
  - `class InstalledPlugin(NamedTuple)` with `plugin: str`, `marketplace: str`, `record: str`.
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
Marketplace content is cloned at its pinned commit into `<repo>/.bcbench/plugins/` (repo-local,
cleaned by `git clean` and an inline clean-before).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from shutil import copytree, rmtree
from typing import NamedTuple

from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations.git_operations import clone_at_commit
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentType

logger = get_logger(__name__)

# NOTE: do NOT import from `bcbench.agent.*` here. `bcbench.agent.__init__` imports the runners,
# which import `bcbench.operations` — importing agent from operations would create a cycle. We
# therefore inline the `.bcbench/plugins` cleanup instead of reusing `remove_agent_plugin`.
_BCBENCH_ROOT = ".bcbench"
_PLUGINS_FOLDER = "plugins"  # under <repo>/.bcbench/plugins/
_MARKETPLACE_MANIFESTS = (".claude-plugin/marketplace.json", ".github/plugin/marketplace.json")


class InstalledPlugin(NamedTuple):
    plugin: str
    marketplace: str
    record: str  # "<name>@<commit>" (marketplace) or "<name>@local"


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_operations.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/operations/plugin_operations.py tests/test_plugin_operations.py
git commit -m "feat: add plugin materialize + marketplace-name helpers"
```

---

### Task 4: `plugin_operations.py` — setup + teardown commands

**Files:**
- Modify: `src/bcbench/operations/plugin_operations.py`
- Modify: `src/bcbench/operations/__init__.py` (exports)
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `InstalledPlugin`, `_materialize`, `_read_marketplace_name` (Task 3); `AgentType`.
- Produces:
  - `setup_plugins_from_config(agent_config: dict, entry: BaseDatasetEntry, repo_path: Path, agent_type: AgentType, cli_cmd: str) -> list[InstalledPlugin]`
  - `teardown_plugins(cli_cmd: str, agent_type: AgentType, installed: list[InstalledPlugin]) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin_operations.py`:

```python
from unittest.mock import call

from bcbench.types import AgentType


class _Recorder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)

        class _R:
            returncode = 0

        return _R()


def _marketplace_entry_cfg():
    return {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}


def test_setup_no_plugins_returns_empty(tmp_path):
    installed = po.setup_plugins_from_config({}, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert installed == []


def test_setup_disabled_entry_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(po.subprocess, "run", _Recorder())
    cfg = {"plugins": [{**_marketplace_entry_cfg(), "enabled": False}]}
    installed = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert installed == []


def test_setup_installs_and_records(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    rec = _Recorder()
    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    monkeypatch.setattr(po.subprocess, "run", rec)

    cfg = {"plugins": [_marketplace_entry_cfg()]}
    installed = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")

    assert installed == [po.InstalledPlugin(plugin="probe-plugin", marketplace="awesome-copilot", record="probe-plugin@" + "a" * 40)]
    # marketplace add + install were issued (self-heal remove/uninstall may precede them)
    assert ["copilot", "plugin", "marketplace", "add", str(tmp_path / ".bcbench" / "plugins" / "github-awesome-copilot")] in rec.calls
    assert ["copilot", "plugin", "install", "probe-plugin@awesome-copilot"] in rec.calls


def test_setup_failure_tears_down_partial_and_raises(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)

    def flaky_run(args, **kwargs):
        class _R:
            returncode = 0

        if args[:4] == ["copilot", "plugin", "marketplace", "add"]:
            raise po.subprocess.CalledProcessError(1, args)
        return _R()

    monkeypatch.setattr(po.subprocess, "run", flaky_run)
    cfg = {"plugins": [_marketplace_entry_cfg()]}

    with pytest.raises(AgentError, match="Plugin setup failed"):
        po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")


def test_teardown_copilot_uninstalls_by_name(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(po.subprocess, "run", rec)
    installed = [po.InstalledPlugin("probe-plugin", "awesome-copilot", "probe-plugin@abc")]

    po.teardown_plugins("copilot", AgentType.COPILOT, installed)

    assert ["copilot", "plugin", "uninstall", "probe-plugin"] in rec.calls
    assert ["copilot", "plugin", "marketplace", "remove", "awesome-copilot"] in rec.calls


def test_teardown_claude_uninstalls_by_qualified_name(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(po.subprocess, "run", rec)
    installed = [po.InstalledPlugin("probe-plugin", "awesome-copilot", "probe-plugin@abc")]

    po.teardown_plugins("claude", AgentType.CLAUDE, installed)

    assert ["claude", "plugin", "uninstall", "probe-plugin@awesome-copilot"] in rec.calls
    assert ["claude", "plugin", "marketplace", "remove", "awesome-copilot"] in rec.calls


def test_teardown_empty_is_noop(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(po.subprocess, "run", rec)
    po.teardown_plugins("copilot", AgentType.COPILOT, [])
    assert rec.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugin_operations.py -k "setup or teardown" -v`
Expected: FAIL — `AttributeError: module 'bcbench.operations.plugin_operations' has no attribute 'setup_plugins_from_config'`.

- [ ] **Step 3: Implement setup + teardown**

Append to `src/bcbench/operations/plugin_operations.py`:

```python
def _run_plugin_cmd(cli_cmd: str, args: list[str], *, check: bool) -> None:
    subprocess.run([cli_cmd, "plugin", *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=check)


def _uninstall_args(agent_type: AgentType, plugin: str, marketplace: str) -> list[str]:
    # Copilot uninstalls by plugin name; Claude by "<plugin>@<marketplace>" (both verified live).
    match agent_type:
        case AgentType.COPILOT:
            return ["uninstall", plugin]
        case AgentType.CLAUDE:
            return ["uninstall", f"{plugin}@{marketplace}"]
        case _:
            raise AgentError(f"Unsupported agent type for plugin teardown: {agent_type}")


def setup_plugins_from_config(agent_config: dict, entry: BaseDatasetEntry, repo_path: Path, agent_type: AgentType, cli_cmd: str) -> list[InstalledPlugin]:
    """Install every enabled plugin entry into the CLI, before the agent launches.

    Returns the installed plugins (for recording and teardown). Raises AgentError on failure
    (after tearing down any partial installs). Skips silently when no entry is enabled.
    """
    entries = [e for e in (agent_config.get("plugins") or []) if e.get("enabled", True)]
    if not entries:
        return []

    plugins_root = repo_path / _BCBENCH_ROOT / _PLUGINS_FOLDER
    if plugins_root.exists():
        rmtree(plugins_root)  # clean-before: wipe stale clones
    plugins_root.mkdir(parents=True, exist_ok=True)

    installed: list[InstalledPlugin] = []
    try:
        for entry_cfg in entries:
            marketplace_dir, record_suffix = _materialize(entry_cfg, entry, plugins_root)
            marketplace_name = _read_marketplace_name(marketplace_dir)

            # self-heal: drop any stale registration left by a crashed prior run (best-effort)
            for plugin in entry_cfg["plugins"]:
                _run_plugin_cmd(cli_cmd, _uninstall_args(agent_type, plugin, marketplace_name), check=False)
            _run_plugin_cmd(cli_cmd, ["marketplace", "remove", marketplace_name], check=False)

            _run_plugin_cmd(cli_cmd, ["marketplace", "add", str(marketplace_dir)], check=True)
            for plugin in entry_cfg["plugins"]:
                _run_plugin_cmd(cli_cmd, ["install", f"{plugin}@{marketplace_name}"], check=True)
                installed.append(InstalledPlugin(plugin=plugin, marketplace=marketplace_name, record=f"{plugin}@{record_suffix}"))
                logger.info(f"Installed plugin {plugin}@{marketplace_name}")
    except (subprocess.CalledProcessError, OSError) as e:
        teardown_plugins(cli_cmd, agent_type, installed)
        raise AgentError(f"Plugin setup failed: {e}") from e

    return installed


def teardown_plugins(cli_cmd: str, agent_type: AgentType, installed: list[InstalledPlugin]) -> None:
    """Uninstall plugins and remove their marketplaces (best-effort; never raises)."""
    if not installed:
        return
    for p in installed:
        _run_plugin_cmd(cli_cmd, _uninstall_args(agent_type, p.plugin, p.marketplace), check=False)
    for marketplace in dict.fromkeys(p.marketplace for p in installed):
        _run_plugin_cmd(cli_cmd, ["marketplace", "remove", marketplace], check=False)
    logger.info(f"Tore down plugins: {[p.record for p in installed]}")
```

In `src/bcbench/operations/__init__.py`, add the imports and `__all__` entries (keep alphabetized within the block):

```python
from bcbench.operations.plugin_operations import setup_plugins_from_config, teardown_plugins
```

```python
    "setup_hooks",
    "setup_instructions_from_config",
    "setup_plugins_from_config",
    "setup_repo_prebuild",
    "stage_and_get_diff",
    "teardown_plugins",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_operations.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/operations/plugin_operations.py src/bcbench/operations/__init__.py tests/test_plugin_operations.py
git commit -m "feat: install/teardown plugins via CLI commands (user scope, both agents)"
```

---

### Task 5: Wire plugin setup/teardown into the Copilot runner

**Files:**
- Modify: `src/bcbench/agent/copilot/agent.py`
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `setup_plugins_from_config`, `teardown_plugins` (Task 4); `ExperimentConfiguration.plugins` (Task 1).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_operations.py`:

```python
from unittest.mock import MagicMock, patch

from bcbench.dataset import BaseDatasetEntry


@patch("bcbench.agent.copilot.agent.teardown_plugins")
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
def test_copilot_runner_records_plugins_and_tears_down(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, mock_teardown, tmp_path
):
    from bcbench.agent.copilot.agent import run_copilot_agent
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stderr=b"")
    mock_setup.return_value = [po.InstalledPlugin("frontend-web-dev", "awesome-copilot", "frontend-web-dev@a1b2c3d4")]
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_copilot_agent(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    mock_teardown.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_operations.py -k copilot_runner -v`
Expected: FAIL — `AttributeError`/`ImportError` for `setup_plugins_from_config` in `bcbench.agent.copilot.agent` (not imported/wired yet), or `config.plugins` is `None`.

- [ ] **Step 3: Wire the runner**

In `src/bcbench/agent/copilot/agent.py`, update the operations import line to include the new functions:

```python
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config, setup_plugins_from_config, teardown_plugins
```

Resolve the CLI binary **before** the plugin setup and reuse it for the launch. Replace the existing block that computes `config`/finds `copilot_cmd` so it reads:

```python
    tool_log_path: Path = setup_hooks(repo_path, AgentType.COPILOT, output_dir)

    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes PowerShell,
    # which re-parses arguments and corrupts prompts containing double quotes (e.g. JSON examples).
    copilot_cmd = shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    installed_plugins = setup_plugins_from_config(copilot_config, entry, repo_path, AgentType.COPILOT, copilot_cmd)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[p.record for p in installed_plugins] or None,
    )

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")
```

Then delete the now-duplicate `copilot_cmd = shutil.which(...)` / `if not copilot_cmd: raise AgentError(...)` block that currently sits just before the `try:` (it has moved up).

Wrap the agent subprocess in a `finally` that tears the plugins down. Change the `try:` that runs the agent so it ends with:

```python
        return metrics, config
    except subprocess.TimeoutExpired:
        logger.exception(f"Copilot CLI timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Copilot CLI timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running Copilot CLI")
        raise
    finally:
        teardown_plugins(copilot_cmd, AgentType.COPILOT, installed_plugins)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugin_operations.py -k copilot_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/agent/copilot/agent.py tests/test_plugin_operations.py
git commit -m "feat: install plugins in the Copilot runner and tear down after the run"
```

---

### Task 6: Wire plugin setup/teardown into the Claude runner

**Files:**
- Modify: `src/bcbench/agent/claude/agent.py`
- Test: `tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `setup_plugins_from_config`, `teardown_plugins`; `ExperimentConfiguration.plugins`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_operations.py`:

```python
@patch("bcbench.agent.claude.agent.teardown_plugins")
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
def test_claude_runner_records_plugins_and_tears_down(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, mock_teardown, tmp_path
):
    from bcbench.agent.claude.agent import run_claude_code
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stdout=b'{"result": "ok"}')
    mock_setup.return_value = [po.InstalledPlugin("frontend-web-dev", "awesome-copilot", "frontend-web-dev@a1b2c3d4")]
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_claude_code(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    mock_teardown.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_operations.py -k claude_runner -v`
Expected: FAIL — `setup_plugins_from_config` not wired in `bcbench.agent.claude.agent`, or `config.plugins is None`.

- [ ] **Step 3: Wire the runner**

In `src/bcbench/agent/claude/agent.py`, update the operations import:

```python
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config, setup_plugins_from_config, teardown_plugins
```

Resolve the CLI binary before plugin setup and reuse it. Replace the block that builds `config` and finds `claude_cmd` so it reads:

```python
    tool_log_path: Path = setup_hooks(repo_path, AgentType.CLAUDE, output_dir)

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

    installed_plugins = setup_plugins_from_config(claude_config, entry, repo_path, AgentType.CLAUDE, claude_cmd)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[p.record for p in installed_plugins] or None,
    )

    logger.info(f"Executing Claude Code in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")
```

Then delete the now-duplicate `claude_cmd = shutil.which("claude")` / `if not claude_cmd: raise AgentError(...)` block that currently sits just before the `try:`.

Add a `finally` to the agent-run `try` block so it ends with:

```python
        return metrics, config
    except subprocess.TimeoutExpired:
        logger.exception(f"Claude Code timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Claude Code execution failed with error {e.stderr}")
        raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
    except Exception:
        logger.exception("Unexpected error running Claude Code")
        raise
    finally:
        teardown_plugins(claude_cmd, AgentType.CLAUDE, installed_plugins)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugin_operations.py -k claude_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bcbench/agent/claude/agent.py tests/test_plugin_operations.py
git commit -m "feat: install plugins in the Claude runner and tear down after the run"
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
# each enabled entry is installed via the CLI's `plugin marketplace add` + `plugin install`
# (user scope, both Copilot and Claude), then uninstalled after the run. Marketplace content is
# cloned at the pinned commit into <repo>/.bcbench/plugins/ (removed by the existing cleanup).
# NOTE: config injection (extraKnownMarketplaces/enabledPlugins) is trust-dialog-gated and
#       ignored in headless mode, so we drive the real CLI commands instead.
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
| `plugins` | _(empty)_ | List of agent plugins to install for the run (marketplace pinned to a commit, or local). Each enabled entry is installed via the CLI's `plugin marketplace add` + `plugin install` and removed afterward. |
```

And add this subsection after the "Custom instructions / skills / custom agents" subsection:

```markdown
### Marketplace & local plugins

`plugins` is a list; each entry is toggled by its own `enabled` (default `true`):

- `source: marketplace` — `repo` (`owner/repo` or git URL) + `commit` (pinned for reproducibility) + `plugins` (names to install).
- `source: local` — `path` (relative to `instructions/<owner>-<repo>/`, pointing at a marketplace root with `.claude-plugin/marketplace.json`) + `plugins`.

At runtime the marketplace is cloned at its commit into `<repo>/.bcbench/plugins/`, installed with the CLI's own commands (user scope), and uninstalled after the run. Installed plugins are recorded in the result's `ExperimentConfiguration.plugins` as `"<name>@<commit>"` / `"<name>@local"`.
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

- **Do not** attempt to load plugins via `extraKnownMarketplaces`/`enabledPlugins` injection — verified (and confirmed by gist `alexey-pelykh/566a4e5160b305db703d543312a1e686`) to be ignored in headless mode.
- The full lifecycle (`marketplace add` → `install` → `uninstall` → `marketplace remove`) was verified live on both CLIs against a local marketplace: non-interactive, offline, exit 0, baseline restored. Copilot uninstalls by `<plugin>`; Claude by `<plugin>@<marketplace>` — `_uninstall_args` encodes this.
- `git fetch --depth 1 origin <sha>` works on GitHub (arbitrary SHA fetch is allowed). If a target host disallows it, the clone will fail loudly and surface as `AgentError` — acceptable (fails the entry like other setup failures).
- Setup ordering: `setup_plugins_from_config` runs after `setup_hooks` and other `setup_*` — it does not touch `.github`/`.claude`, so instruction/skill setup is unaffected.
