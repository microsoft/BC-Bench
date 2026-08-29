"""Harms testing for BCAL: inject harms through direct (UPIA) and indirect (XPIA) vectors and score them."""

from bcbench.harms.case import Detector, HarmsCase, HarmsChannel, HarmsVector, Placement
from bcbench.harms.couching import DEFAULT_COUCHINGS, CouchingTemplate, couchings_by_id
from bcbench.harms.evaluate import evaluate_trials
from bcbench.harms.harvest import harvest_objectives
from bcbench.harms.runner import HarmsTrial, annotate_trials, harm_delivered_for, run_harms_suite, write_trials
from bcbench.harms.score import reconcile, score_trial, score_trials
from bcbench.harms.sources import AttackObjective, HarmsCaseSource, ManualHarmsSource, RedTeamHarmsSource, load_objectives

__all__ = [
    "DEFAULT_COUCHINGS",
    "AttackObjective",
    "CouchingTemplate",
    "Detector",
    "HarmsCase",
    "HarmsCaseSource",
    "HarmsChannel",
    "HarmsTrial",
    "HarmsVector",
    "ManualHarmsSource",
    "Placement",
    "RedTeamHarmsSource",
    "annotate_trials",
    "couchings_by_id",
    "evaluate_trials",
    "harm_delivered_for",
    "harvest_objectives",
    "load_objectives",
    "reconcile",
    "run_harms_suite",
    "score_trial",
    "score_trials",
    "write_trials",
]
