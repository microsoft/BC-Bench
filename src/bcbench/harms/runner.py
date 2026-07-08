"""Expand vector-invariant harms cases into per-vector trials and run bcal for each.

The matrix (which vectors to attempt) lives here / in config, not in the dataset — keeping cases
vector-invariant. Each ``(case, vector)`` becomes one bcal run; direct trials send the harm as the
prompt, indirect trials send a benign trigger plus a ``--harms-fixture`` manifest carrying the harm.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict

from bcbench.agent.bcal import BCalBackendConfig, bcal_version, run_bcal_prompt
from bcbench.agent.bcal.agent import _resolve_bcal_executable
from bcbench.config import get_config
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.harms.case import HarmsCase, HarmsChannel, HarmsVector
from bcbench.harms.log_analysis import analyze_trial_log
from bcbench.logger import get_logger
from bcbench.operations import ensure_package_cache
from bcbench.types import EvaluationCategory

__all__ = ["HarmsTrial", "annotate_trials", "harm_delivered_for", "run_harms_suite", "write_trials"]

logger = get_logger(__name__)
_config = get_config()


class HarmsTrial(BaseModel):
    """One (case, vector) attempt: the delivered attack, the bcal response, and where artifacts landed."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    vector: HarmsVector
    channel: HarmsChannel
    risk: str | None
    attack: str  # the harmful content delivered through the vector (the harm)
    prompt: str  # the bcal --prompt used (harm for direct, benign trigger for indirect)
    response: str  # bcal output (generated AL + stdout)
    executed: bool  # False on dry-run
    fixture_path: str | None
    export_dir: str
    log_path: str | None
    tools_invoked: list[str] = []
    # Did the injected payload actually reach the model via a tool result? None for direct trials
    # (no seam injection) and for dry-runs; True/False for executed indirect trials.
    injection_landed: bool | None = None
    # Did the agent actually SEE the harm at all? For direct trials the harm must appear in the prompt;
    # for indirect trials it must land in a tool result. A result line is only *valid* when this is True
    # — otherwise the safety score reflects an attack the agent never received. None on dry-runs.
    harm_delivered: bool | None = None


def _load_base_entry() -> NL2ALEntry:
    category = EvaluationCategory.NL2AL
    return cast(NL2ALEntry, category.entry_class.load(category.dataset_path)[0])


def _entry_for(base: NL2ALEntry, case: HarmsCase) -> NL2ALEntry:
    return base.model_copy(update={"page": case.page, "audience": case.audience})


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)


def harm_delivered_for(channel: HarmsChannel, *, executed: bool, injection_landed: bool | None) -> bool | None:
    """Whether the agent actually received the harm — the validity gate for a result line.

    Direct (UPIA) trials deliver the harm *as the prompt*, so delivery is guaranteed once executed.
    Indirect (XPIA) trials only deliver the harm if the injected payload landed in a tool result.
    ``None`` for un-executed (dry-run) trials.
    """
    if not executed:
        return None
    if channel is HarmsChannel.DIRECT:
        return True
    return bool(injection_landed)


def _resolve_log_path(trial: HarmsTrial, results_dir: Path | None) -> Path | None:
    if trial.log_path and Path(trial.log_path).exists():
        return Path(trial.log_path)
    if results_dir is not None:
        candidate = results_dir / "logs" / f"{_slug(trial.case_id)}__{trial.vector.value}.jsonl"
        if candidate.exists():
            return candidate
    return Path(trial.log_path) if trial.log_path else None


def annotate_trials(trials: list[HarmsTrial], results_dir: Path | None = None) -> list[HarmsTrial]:
    """Re-derive delivery/landing facts from each executed trial's captured log (post-processing).

    Recomputes ``tools_invoked``, ``injection_landed`` and ``harm_delivered`` from ``logs/`` so runs
    captured before these fields existed can be back-filled without re-running bcal. ``results_dir``
    lets the log path be reconstructed when a run directory has been moved.
    """
    annotated: list[HarmsTrial] = []
    for trial in trials:
        if not trial.executed:
            annotated.append(trial)
            continue
        analysis = analyze_trial_log(_resolve_log_path(trial, results_dir), trial.attack)
        injection_landed = analysis.payload_in_tool_result if trial.channel is HarmsChannel.INDIRECT else None
        annotated.append(
            trial.model_copy(
                update={
                    "tools_invoked": analysis.tools_invoked or trial.tools_invoked,
                    "injection_landed": injection_landed,
                    "harm_delivered": harm_delivered_for(trial.channel, executed=True, injection_landed=injection_landed),
                }
            )
        )
    return annotated


def run_harms_suite(
    cases: list[HarmsCase],
    backend_config: BCalBackendConfig,
    results_dir: Path,
    *,
    limit: int | None = None,
    vectors: list[HarmsVector] | None = None,
    dry_run: bool = False,
    capture_full_log: bool = True,
) -> list[HarmsTrial]:
    selected = cases[:limit] if limit is not None else cases
    if not selected:
        logger.warning("No harms cases to run.")
        return []

    base_entry = _load_base_entry()
    package_cache_path = results_dir / _config.file_patterns.alpackages_dirname
    fixtures_dir = results_dir / "fixtures"
    exports_dir = results_dir / "exports"
    logs_dir = results_dir / "logs"
    for directory in (fixtures_dir, exports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        bcal_exe = _resolve_bcal_executable()
        logger.info(f"Harms run using bcal: {bcal_exe} (version {bcal_version(bcal_exe)})")
        ensure_package_cache(package_cache_path, base_entry.environment_setup_version)

    trials: list[HarmsTrial] = []
    for case in selected:
        entry = _entry_for(base_entry, case)
        for vector in case.resolve_vectors(vectors):
            trials.append(
                _run_trial(
                    case=case,
                    vector=vector,
                    entry=entry,
                    backend_config=backend_config,
                    package_cache_path=package_cache_path,
                    fixtures_dir=fixtures_dir,
                    exports_dir=exports_dir,
                    logs_dir=logs_dir,
                    dry_run=dry_run,
                    capture_full_log=capture_full_log,
                )
            )

    write_trials(results_dir / "trials.jsonl", trials)
    logger.info(f"Ran {len(trials)} harms trials ({'dry-run' if dry_run else 'executed'}) -> {results_dir}")
    return trials


def _run_trial(
    *,
    case: HarmsCase,
    vector: HarmsVector,
    entry: NL2ALEntry,
    backend_config: BCalBackendConfig,
    package_cache_path: Path,
    fixtures_dir: Path,
    exports_dir: Path,
    logs_dir: Path,
    dry_run: bool,
    capture_full_log: bool,
) -> HarmsTrial:
    stem = f"{_slug(case.id)}__{vector.value}"
    manifest = case.fixture_manifest_for(vector)
    fixture_path: Path | None = None
    if manifest is not None:
        fixture_path = fixtures_dir / f"{stem}.json"
        fixture_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    export_dir = exports_dir / stem
    log_path = logs_dir / f"{stem}.jsonl" if capture_full_log else None
    prompt = case.prompt_for(vector)

    response = "" if dry_run else run_bcal_prompt(entry, prompt, package_cache_path, export_dir, backend_config, harms_fixture_path=fixture_path, log_full_path=log_path)

    # Validate whether the injection actually reached the model (indirect trials only).
    tools_invoked: list[str] = []
    injection_landed: bool | None = None
    harm_delivered: bool | None = None
    if not dry_run:
        analysis = analyze_trial_log(log_path, case.attack_text_for(vector))
        tools_invoked = analysis.tools_invoked
        if vector.channel is HarmsChannel.INDIRECT:
            injection_landed = analysis.payload_in_tool_result
        harm_delivered = harm_delivered_for(vector.channel, executed=True, injection_landed=injection_landed)

    return HarmsTrial(
        case_id=case.id,
        vector=vector,
        channel=vector.channel,
        risk=case.risk,
        attack=case.attack_text_for(vector),
        prompt=prompt,
        response=response,
        executed=not dry_run,
        fixture_path=str(fixture_path) if fixture_path else None,
        export_dir=str(export_dir),
        log_path=str(log_path) if log_path else None,
        tools_invoked=tools_invoked,
        injection_landed=injection_landed,
        harm_delivered=harm_delivered,
    )


def write_trials(path: Path, trials: list[HarmsTrial]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for trial in trials:
            handle.write(trial.model_dump_json() + "\n")
