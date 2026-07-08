"""Contamination / memorization probes for the BC-Bench dataset.

The file-path identification probe follows the SWE-Bench Illusion methodology
(arXiv:2506.12286): give a model only the bug report, withhold the repository,
and ask which file(s) contain the bug. A model that answers correctly without
the codebase is exhibiting memorization. Because Business Central AL has rigid
file-naming conventions, absolute accuracy is only meaningful relative to a
control set (see ``split_by_cutoff``): the contamination signal is the drop
between potentially-contaminated (old/public) and control (fresh) entries.
"""

from bcbench.contamination.filepath_probe import (
    FilePathProbeResult,
    FilePathProbeScore,
    ProbeAggregate,
    aggregate_results,
    build_probe_prompt,
    extract_gold_files,
    parse_prediction,
    score_prediction,
    split_by_cutoff,
)
from bcbench.contamination.runner import load_probe_results, run_filepath_probe, save_probe_result

__all__ = [
    "FilePathProbeResult",
    "FilePathProbeScore",
    "ProbeAggregate",
    "aggregate_results",
    "build_probe_prompt",
    "extract_gold_files",
    "load_probe_results",
    "parse_prediction",
    "run_filepath_probe",
    "save_probe_result",
    "score_prediction",
    "split_by_cutoff",
]
