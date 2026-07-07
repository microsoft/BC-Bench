"""Harms testing for BCAL: inject harms through direct (UPIA) and indirect (XPIA) vectors and score them."""

from bcbench.harms.case import HarmsCase, HarmsChannel, HarmsVector, Placement
from bcbench.harms.couching import DEFAULT_COUCHINGS, CouchingTemplate, couchings_by_id
from bcbench.harms.evaluate import evaluate_trials
from bcbench.harms.harvest import harvest_objectives
from bcbench.harms.runner import HarmsTrial, run_harms_suite
from bcbench.harms.sources import AttackObjective, HarmsCaseSource, ManualHarmsSource, RedTeamHarmsSource, load_objectives

__all__ = [
    "DEFAULT_COUCHINGS",
    "AttackObjective",
    "CouchingTemplate",
    "HarmsCase",
    "HarmsCaseSource",
    "HarmsChannel",
    "HarmsTrial",
    "HarmsVector",
    "ManualHarmsSource",
    "Placement",
    "RedTeamHarmsSource",
    "couchings_by_id",
    "evaluate_trials",
    "harvest_objectives",
    "load_objectives",
    "run_harms_suite",
]
