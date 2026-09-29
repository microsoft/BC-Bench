"""Collection module for gathering dataset entries from GitHub."""

from bcbench.collection.collect_codereview import collect_codereview_entries
from bcbench.collection.collect_gh import ScreeningResult, collect_gh_entry, screen_gh_candidate

__all__ = [
    "ScreeningResult",
    "collect_codereview_entries",
    "collect_gh_entry",
    "screen_gh_candidate",
]
