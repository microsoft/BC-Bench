from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bcbench.agent.bcal.harms.case import HarmsCase


class _Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: dict[str, object] = Field(default_factory=dict)
    cases: list[dict[str, object]] = Field(min_length=1)


def load_suite(path: Path) -> list[HarmsCase]:
    suite = _Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    cases = [HarmsCase.model_validate(suite.defaults | case) for case in suite.cases]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError(f"Duplicate NL2AL harms case ids in {path}")
    return cases
