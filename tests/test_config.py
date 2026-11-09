import pytest
import yaml
from pydantic import ValidationError

from bcbench.config import JudgeConfig


@pytest.mark.parametrize(
    "judges",
    [
        {"code-review": {}, "lm-checklist": {"model": "lm-model"}},
        {"code-review": {"model": "unknown-model"}, "lm-checklist": {"model": "lm-model"}},
        {"code-review": {"model": "gpt-5.3-codex"}, "lm-checklist": {"model": " "}},
    ],
)
def test_judge_config_requires_models(tmp_path, judges):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"judges": judges}), encoding="utf-8")

    with pytest.raises(ValidationError):
        JudgeConfig.from_file(config_path)
