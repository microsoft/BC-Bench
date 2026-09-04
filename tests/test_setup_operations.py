import json
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from bcbench.dataset import BugFixEntry
from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version, setup_repo_prebuild
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


class TestSetRuntimeVersion:
    def test_sets_runtime_from_platform(self, tmp_path):
        app_json = {"platform": "25.0.0.0", "version": "25.0.0.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        set_runtime_version(tmp_path, ["."])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "14.0"

    def test_skips_when_runtime_already_set(self, tmp_path):
        app_json = {"platform": "25.0.0.0", "runtime": "12.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        set_runtime_version(tmp_path, [str(tmp_path)])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "12.0"

    def test_platform_27_maps_to_runtime_16(self, tmp_path):
        app_json = {"platform": "27.0.0.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        set_runtime_version(tmp_path, [str(tmp_path)])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "16.0"

    def test_skips_missing_app_json(self, tmp_path):
        set_runtime_version(tmp_path, [str(tmp_path)])  # should not raise


def test_setup_repo_prebuild_commits_scope_compatibility_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "App"
    project.mkdir(parents=True)
    table = project / "Example.Table.al"
    table.write_bytes(b"\xef\xbb\xbftable 50100 Example\r\n{\r\n    Scope = OnPrem;\r\n}\r\n")
    outside = repo / "Outside.Table.al"
    outside.write_text("table 50101 Outside\n{\n    Scope = OnPrem;\n}\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "base"],
        cwd=repo,
        check=True,
    )
    base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, encoding="utf-8", text=True, check=True).stdout.strip()

    setup_repo_prebuild(create_dataset_entry(base_commit=base_commit, project_paths=["App"]), repo)

    assert "Scope = OnPrem;" not in table.read_text(encoding="utf-8-sig")
    assert "Scope = OnPrem;" in outside.read_text(encoding="utf-8")
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, encoding="utf-8", text=True, check=True).stdout == ""
    assert subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, encoding="utf-8", text=True, check=True).stdout.strip() == "Remove 1 Scope = OnPrem declaration(s)"


def test_benchmark_patches_do_not_depend_on_removed_scope_lines() -> None:
    for entry in BugFixEntry.load(EvaluationCategory.BUG_FIX.dataset_path):
        for patch in (entry.patch, entry.test_patch):
            assert re.search(r"(?im)^[-+ ]\s*Scope\s*=\s*OnPrem;", patch) is None, entry.instance_id


class TestBootstrapAppJson:
    def test_writes_manifest_with_derived_versions(self, tmp_path):
        path = bootstrap_app_json(tmp_path / "app", "BC-Bench Query", "26.0.12345.0")

        manifest = json.loads(path.read_text())
        assert path == tmp_path / "app" / "app.json"
        assert manifest["name"] == "BC-Bench Query"
        assert manifest["publisher"] == "BC-Bench"
        assert manifest["platform"] == manifest["application"] == "26.0.0.0"
        assert manifest["runtime"] == "15.0"
        assert manifest["target"] == "OnPrem"
        assert manifest["idRanges"] == [{"from": 50100, "to": 50149}]
        assert uuid.UUID(manifest["id"])

    def test_overrides_are_applied(self, tmp_path):
        app_id = "1e6a4e1f-4b0e-4b1f-9d0a-1a2b3c4d5e6f"
        path = bootstrap_app_json(
            tmp_path,
            "Custom",
            "25.0",
            id_range=(50000, 50001),
            publisher="Contoso",
            app_version="2.1.0.0",
            target="Cloud",
            app_id=app_id,
        )

        manifest = json.loads(path.read_text())
        assert manifest["id"] == app_id
        assert manifest["publisher"] == "Contoso"
        assert manifest["version"] == "2.1.0.0"
        assert manifest["target"] == "Cloud"
        assert manifest["idRanges"] == [{"from": 50000, "to": 50001}]

    def test_omits_runtime_when_platform_too_old(self, tmp_path):
        manifest = json.loads(bootstrap_app_json(tmp_path, "Old", "10.0.0.0").read_text())

        assert "runtime" not in manifest

    def test_rejects_unparsable_version(self, tmp_path):
        with pytest.raises(ValueError, match="major version"):
            bootstrap_app_json(tmp_path, "Bad", "not-a-version")

    def test_rejects_inverted_id_range(self, tmp_path):
        with pytest.raises(ValueError, match="id_range"):
            bootstrap_app_json(tmp_path, "Bad", "26.0", id_range=(50200, 50100))
