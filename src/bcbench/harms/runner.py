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

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_prompt
from bcbench.config import get_config
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.harms.case import HarmsCase, HarmsChannel, HarmsVector
from bcbench.logger import get_logger
from bcbench.operations import ensure_package_cache
from bcbench.types import EvaluationCategory

__all__ = ["HarmsTrial", "run_harms_suite"]

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


def _load_base_entry() -> NL2ALEntry:
    category = EvaluationCategory.NL2AL
    return cast(NL2ALEntry, category.entry_class.load(category.dataset_path)[0])


def _entry_for(base: NL2ALEntry, case: HarmsCase) -> NL2ALEntry:
    return base.model_copy(update={"page": case.page, "audience": case.audience})


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)


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

    _write_trials(results_dir / "trials.jsonl", trials)
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
    )


def _write_trials(path: Path, trials: list[HarmsTrial]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for trial in trials:
            handle.write(trial.model_dump_json() + "\n")
