import json
import uuid

import pytest

from bcbench.operations.setup_operations import bootstrap_app_json, set_runtime_version


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
