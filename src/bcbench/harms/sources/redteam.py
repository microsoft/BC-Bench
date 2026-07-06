"""Red-team harms source — interface stub for a future adaptor.

The runner is source-agnostic: it consumes ``HarmsCase`` objects. A future adaptor will turn
red-team-generated attack objectives (e.g. the Azure AI Evaluation RedTeam SDK's seed prompts /
generated objectives) into vector-invariant ``HarmsCase`` objects, so the same expansion + scoring
pipeline covers automated harms. It is intentionally **not implemented** yet — this file documents
the seam and keeps ``harms`` decoupled from ``redteam``.

Sketch of the eventual implementation::

    class RedTeamHarmsSource:
        def __init__(self, objectives: Iterable[AttackObjective], page: str, audience: str) -> None: ...

        def load(self) -> list[HarmsCase]:
            # map each generated objective's harmful content -> HarmsCase.harm,
            # attach a benign trigger + page/audience, leave vectors unset (full matrix).
            ...
"""

from __future__ import annotations

from bcbench.harms.case import HarmsCase

__all__ = ["RedTeamHarmsSource"]


class RedTeamHarmsSource:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise NotImplementedError("RedTeamHarmsSource is not implemented yet. Author harms cases manually via a YAML suite (bcbench.harms.sources.manual.ManualHarmsSource) for now.")

    def load(self) -> list[HarmsCase]:
        raise NotImplementedError
