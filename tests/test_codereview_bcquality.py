"""Tests for live BCQuality consumption (code-review category)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from bcbench.agent.shared.codereview_bcquality import (
    BCQualityConfig,
    build_bootstrap_prompt,
    build_task_context,
    filter_clone,
    glob_match,
    parse_bcquality_config,
)
from bcbench.config import get_config

_PINNED_SHA = "822cae1b2771ac25f665f73369f69093bd4fd630"

_BASE_CONFIG = BCQualityConfig(
    enabled=True,
    repo="https://github.com/microsoft/BCQuality",
    ref=_PINNED_SHA,
    enabled_layers=("microsoft",),
    disabled_skills=(),
    knowledge_allow=("microsoft/knowledge/**",),
    knowledge_deny=(),
    task_context={"technologies": ("al",), "countries": ("w1",)},
)


def _enabled_config(**overrides) -> BCQualityConfig:
    return replace(_BASE_CONFIG, **overrides)


class TestParseConfig:
    def test_returns_none_when_section_missing(self):
        assert parse_bcquality_config({}) is None

    def test_parses_full_section(self):
        raw = {
            "bcquality": {
                "enabled": True,
                "repo": "https://github.com/microsoft/BCQuality",
                "ref": _PINNED_SHA,
                "enabled-layers": ["microsoft"],
                "disabled-skills": [],
                "knowledge": {"allow": ["microsoft/knowledge/**"], "deny": []},
                "task-context": {"technologies": ["al"], "countries": ["w1"], "application-area": ["all"], "bc-version": ["all"]},
            }
        }
        config = parse_bcquality_config(raw)

        assert config is not None
        assert config.enabled is True
        assert config.ref == _PINNED_SHA
        assert config.enabled_layers == ("microsoft",)
        assert config.knowledge_allow == ("microsoft/knowledge/**",)
        assert config.task_context["technologies"] == ("al",)
        assert config.task_context["application-area"] == ("all",)

    def test_unknown_layer_raises(self):
        with pytest.raises(ValueError, match="enabled-layers"):
            parse_bcquality_config({"bcquality": {"enabled": False, "enabled-layers": ["bogus"]}})

    def test_enabled_with_non_sha_ref_raises(self):
        with pytest.raises(ValueError, match="40-character commit SHA"):
            parse_bcquality_config({"bcquality": {"enabled": True, "repo": "https://github.com/microsoft/BCQuality", "ref": "main"}})

    def test_enabled_with_non_http_repo_raises(self):
        with pytest.raises(ValueError, match="http"):
            parse_bcquality_config({"bcquality": {"enabled": True, "repo": "git@github.com:microsoft/BCQuality.git", "ref": _PINNED_SHA}})

    def test_disabled_skips_sha_enforcement(self):
        config = parse_bcquality_config({"bcquality": {"enabled": False, "repo": "https://x", "ref": "main"}})
        assert config is not None
        assert config.enabled is False


class TestShippedConfigAlignment:
    def test_default_config_yaml_matches_bcapps(self):
        config_file: Path = get_config().paths.agent_share_dir / "config.yaml"
        raw = yaml.safe_load(config_file.read_text())
        config = parse_bcquality_config(raw)

        assert config is not None
        assert config.enabled is False  # vanilla baseline by default
        assert config.repo == "https://github.com/microsoft/BCQuality"
        assert config.ref == _PINNED_SHA
        assert config.enabled_layers == ("microsoft",)
        assert config.disabled_skills == ()
        assert config.knowledge_allow == ("microsoft/knowledge/**",)
        assert config.knowledge_deny == ()
        assert config.task_context["technologies"] == ("al",)
        assert config.task_context["countries"] == ("w1",)


class TestGlobMatch:
    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            ("microsoft/knowledge/a.md", "microsoft/knowledge/**", True),
            ("microsoft/knowledge/sub/a.md", "microsoft/knowledge/**", True),
            ("community/knowledge/a.md", "microsoft/knowledge/**", False),
            ("microsoft/skills/x.md", "microsoft/skills/*.md", True),
            ("microsoft/skills/sub/x.md", "microsoft/skills/*.md", False),
            ("a/b.md", "a/?.md", True),
            ("a/bb.md", "a/?.md", False),
            ("anything", "", False),
        ],
    )
    def test_glob_match(self, path: str, pattern: str, expected: bool):
        assert glob_match(path, pattern) is expected


def _make_bcquality_tree(root: Path) -> None:
    files = [
        "skills/entry.md",
        "skills/read.md",
        "skills/do.md",
        "microsoft/skills/review/al-code-review.md",
        "microsoft/skills/review/al-style-review.md",
        "microsoft/knowledge/security/s.md",
        "microsoft/knowledge/performance/p.md",
        "community/knowledge/c.md",
        "community/skills/review/c-review.md",
    ]
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


class TestFilterClone:
    def test_removes_disabled_layers_keeps_meta_skills(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        report = filter_clone(root, _enabled_config())

        assert (root / "skills" / "entry.md").exists()
        assert (root / "microsoft" / "knowledge" / "security" / "s.md").exists()
        assert (root / "microsoft" / "skills" / "review" / "al-code-review.md").exists()
        assert not (root / "community" / "knowledge" / "c.md").exists()
        assert not (root / "community" / "skills" / "review" / "c-review.md").exists()

        reasons = {(e.path, e.reason) for e in report.removed}
        assert ("community/knowledge/c.md", "layer-disabled") in reasons
        assert ("community/skills/review/c-review.md", "layer-disabled") in reasons

    def test_writes_filter_report(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        filter_clone(root, _enabled_config())

        report_path = root / "_filter-report.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert data["removed_count"] == len(data["removed"])
        assert data["enabled_layers"] == ["microsoft"]

    def test_allow_list_miss_removed(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        filter_clone(root, _enabled_config(knowledge_allow=("microsoft/knowledge/security/**",)))

        assert (root / "microsoft" / "knowledge" / "security" / "s.md").exists()
        assert not (root / "microsoft" / "knowledge" / "performance" / "p.md").exists()

    def test_deny_list_hit_removed(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        filter_clone(root, _enabled_config(knowledge_deny=("microsoft/knowledge/performance/**",)))

        assert (root / "microsoft" / "knowledge" / "security" / "s.md").exists()
        assert not (root / "microsoft" / "knowledge" / "performance" / "p.md").exists()

    def test_disabled_skill_removed(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        filter_clone(root, _enabled_config(disabled_skills=("microsoft/skills/review/al-style-review.md",)))

        assert (root / "microsoft" / "skills" / "review" / "al-code-review.md").exists()
        assert not (root / "microsoft" / "skills" / "review" / "al-style-review.md").exists()

    def test_path_traversal_disabled_skill_ignored(self, tmp_path: Path):
        root = tmp_path / "bcq"
        _make_bcquality_tree(root)
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")

        filter_clone(root, _enabled_config(disabled_skills=("microsoft/../outside.md",)))

        assert outside.exists()


class TestTaskContext:
    def test_includes_goal_and_dimensions(self):
        context = build_task_context(_enabled_config())

        assert context["goal"] == "review pull request"
        assert context["inputs-available"] == ["pr-diff", "file-path", "repository"]
        assert context["enabled-layers"] == ["microsoft"]
        assert context["technologies"] == ["al"]
        assert context["countries"] == ["w1"]


class TestBootstrapPrompt:
    def _template(self) -> str:
        config_file: Path = get_config().paths.agent_share_dir / "config.yaml"
        raw = yaml.safe_load(config_file.read_text())
        return raw["prompt"]["bcquality-bootstrap-template"]

    def test_contains_contract_and_output_schema(self):
        prompt = build_bootstrap_prompt(self._template(), Path("/repo/under/review"), "_task-context.json", "review.json")

        assert "./skills/entry.md" in prompt
        assert "_task-context.json" in prompt
        assert "review.json" in prompt
        assert "git diff HEAD" in prompt
        assert "blocker, major, minor, or info" in prompt
        assert "/repo/under/review" in prompt
