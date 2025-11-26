"""Collection module for gathering dataset entries from various sources."""

from bcbench.collection.collect_gh import collect_gh_entry
from bcbench.collection.collect_nav import collect_nav_entry

__all__ = ["collect_gh_entry", "collect_nav_entry"]
