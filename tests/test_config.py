import pytest
import yaml

from bcbench.config import JudgeConfig


@pytest.mark.parametrize(
    ("judges", "error"),
    [
        ({"code-review": {}, "lm-checklist": {"model": "lm-model"}}, KeyError),
        ({"code-review": {"model": "code-review-model"}, "lm-checklist": {"model": ""}}, ValueError),
    ],
)
def test_judge_config_requires_models(tmp_path, judges, error):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"judges": judges}), encoding="utf-8")

    with pytest.raises(error):
        JudgeConfig.from_file(config_path)
