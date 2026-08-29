"""Source-agnostic contract for producing harms cases.

The runner consumes ``HarmsCase`` objects regardless of origin. Manual YAML suites implement this
today; a red-team adaptor can implement the same protocol later without changing the runner.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bcbench.harms.case import HarmsCase

__all__ = ["HarmsCaseSource"]


@runtime_checkable
class HarmsCaseSource(Protocol):
    def load(self) -> list[HarmsCase]: ...
