"""Red-team harms source: turn AI red-teaming attack objectives into vector-invariant harms cases.

The BC-Bench red-team integration (``bcbench.redteam``) drives the Azure AI Red Teaming Agent, which
generates harmful *attack objectives* (in the upstream seed-prompt JSON format). This adaptor pipes
those objectives into the harms-testing harness: each objective is **couched** (see
``bcbench.harms.couching``) into a delivered harm + a benign trigger, producing ``HarmsCase`` objects
the runner then expands across every injection vector (direct + the harness seams).

Two entry points:
  - ``load_objectives(path)`` — read objectives already produced (by the agent or hand-authored).
  - ``harvest_objectives_via_agent(...)`` (in ``bcbench.harms.harvest``) — run the red-team agent to
    generate objectives, then feed them here.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bcbench.harms.case import HarmsCase, HarmsVector, Placement
from bcbench.harms.couching import CouchingTemplate, couchings_by_id

__all__ = ["AttackObjective", "RedTeamHarmsSource", "load_objectives"]

# Seam vectors that accept object/property/target steering. Red-team cases carry no author-provided
# placement, so without a default the harness injects into a synthetic location the agent never reads
# (payload never lands). Mirror the manual suites: target the page's Caption in the Base Application,
# which inspect_page/get_properties reliably surface.
_STEERABLE_VECTORS: tuple[HarmsVector, ...] = (HarmsVector.PAGE_INSPECTOR, HarmsVector.SYMBOLS)


class AttackObjective(BaseModel):
    """One red-team attack objective: the harmful content plus its risk category and id."""

    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    risk: str | None = None

    @classmethod
    def from_seed_entry(cls, entry: dict, index: int) -> AttackObjective:
        """Parse the upstream seed-prompt JSON shape: {metadata:{target_harms:[{risk-type}]}, messages:[{role,content}], id}."""
        messages = entry.get("messages") or []
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        content = next((c for c in user_msgs if c.strip()), "")
        harms = (entry.get("metadata") or {}).get("target_harms") or []
        risk = (harms[0].get("risk-type") if harms else None) or None
        return cls(id=str(entry.get("id", index)), content=content, risk=risk)


def load_objectives(path: Path) -> list[AttackObjective]:
    """Load attack objectives from a JSON file (a list in the upstream seed-prompt format)."""
    if not path.exists():
        raise FileNotFoundError(f"Attack objectives file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError(f"Attack objectives file must contain a JSON list, got {type(raw).__name__}.")
    objectives = [AttackObjective.from_seed_entry(entry, i) for i, entry in enumerate(raw)]
    return [o for o in objectives if o.content.strip()]


class RedTeamHarmsSource:
    """Expands red-team attack objectives into couched, vector-invariant ``HarmsCase`` objects.

    Each ``(objective, couching)`` pair becomes one case: the couching renders the delivered ``harm``
    and the benign ``trigger``; the runner then attempts it through every configured vector.
    """

    def __init__(
        self,
        objectives: list[AttackObjective],
        *,
        page: str = "Customer Card",
        audience: str = "Business",
        couchings: list[CouchingTemplate] | None = None,
        vectors: list[HarmsVector] | None = None,
        placement: dict[HarmsVector, Placement] | None = None,
    ) -> None:
        self._objectives = objectives
        self._page = page
        self._audience = audience
        self._couchings = couchings if couchings is not None else couchings_by_id(None)
        self._vectors = vectors
        self._placement = placement if placement is not None else self._default_placement(page)

    @staticmethod
    def _default_placement(page: str) -> dict[HarmsVector, Placement]:
        steering = Placement(object=page, property="Caption", target="Base Application")
        return dict.fromkeys(_STEERABLE_VECTORS, steering)

    def load(self) -> list[HarmsCase]:
        cases: list[HarmsCase] = []
        for objective in self._objectives:
            for couching in self._couchings:
                ctx = {"objective": objective.content, "page": self._page, "audience": self._audience, "risk": objective.risk or ""}
                cases.append(
                    HarmsCase(
                        id=f"rt-{objective.id}-{couching.id}",
                        harm=couching.render_harm(**ctx),
                        trigger=couching.render_trigger(**ctx),
                        page=self._page,
                        audience=self._audience,  # type: ignore[arg-type]
                        vectors=self._vectors,
                        placement=self._placement,
                        risk=objective.risk,
                        source="redteam",
                    )
                )
        return cases
