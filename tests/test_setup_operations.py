import json

from bcbench.operations.setup_operations import set_runtime_version


class TestSetRuntimeVersion:
    def test_sets_runtime_from_platform(self, tmp_path):
        app_json = {"platform": "25.0.0.0", "version": "25.0.0.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        set_runtime_version(tmp_path, [str(tmp_path)])

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
