"""Harms testing for BCAL: inject harms through direct (UPIA) and indirect (XPIA) vectors and score them."""

from bcbench.harms.case import HarmsCase, HarmsChannel, HarmsVector, Placement
from bcbench.harms.evaluate import evaluate_trials
from bcbench.harms.runner import HarmsTrial, run_harms_suite
from bcbench.harms.sources import HarmsCaseSource, ManualHarmsSource

__all__ = [
    "HarmsCase",
    "HarmsCaseSource",
    "HarmsChannel",
    "HarmsTrial",
    "HarmsVector",
    "ManualHarmsSource",
    "Placement",
    "evaluate_trials",
    "run_harms_suite",
]
