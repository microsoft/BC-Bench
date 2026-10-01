"""Collection module for gathering dataset entries from GitHub."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.collection.collect_codereview import collect_codereview_entries
    from bcbench.collection.collect_gh import ScreeningResult, collect_gh_entry, screen_gh_candidate

_LAZY_EXPORTS = {
    "ScreeningResult": "bcbench.collection.collect_gh",
    "collect_codereview_entries": "bcbench.collection.collect_codereview",
    "collect_gh_entry": "bcbench.collection.collect_gh",
    "screen_gh_candidate": "bcbench.collection.collect_gh",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        return getattr(import_module(_LAZY_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ScreeningResult",
    "collect_codereview_entries",
    "collect_gh_entry",
    "screen_gh_candidate",
]
