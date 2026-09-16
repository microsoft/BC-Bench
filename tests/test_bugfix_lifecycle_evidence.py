import json
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_lifecycle import BugFixLifecyclePaths, EvidenceStore, TrustedSource, sha256_file, sha256_text
from bcbench.results.bugfix import BugFixPhaseResult, BugFixPhaseStatus


def _lifecycle_paths(tmp_path: Path) -> BugFixLifecyclePaths:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    return BugFixLifecyclePaths(
        entry_root=entry_root,
        baseline_workspace=entry_root / "baseline",
        agent_workspace=entry_root / "agent",
        agent_logs=entry_root / "agent-logs",
        mounted_staging=entry_root / "staging",
        evaluator_workspaces=entry_root / "evaluators",
        evidence=entry_root / "evidence",
        protected_root=protected_root,
        trusted_source=protected_root / "repository.git",
        checkpoints=protected_root / "checkpoints",
        final_results=protected_root / "final-results",
    )


def _create_junction(junction: Path, target: Path) -> None:
    target.mkdir(parents=True)
    junction.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"Directory junction creation is unavailable: {result.stderr or result.stdout}")


def test_lifecycle_models_are_immutable(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    trusted_source = TrustedSource(repository=paths.trusted_source, commit="a" * 40)

    with pytest.raises(FrozenInstanceError):
        paths.evidence = tmp_path / "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        trusted_source.commit = "b" * 40  # type: ignore[misc]


def test_sha256_helpers_match_known_digest(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("abc", encoding="utf-8")

    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_file(source) == sha256_text("abc")


def test_save_phase_atomically_replaces_complete_json(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    store = EvidenceStore(paths)
    first = BugFixPhaseResult(status=BugFixPhaseStatus.FAILED, error_message="first")
    second = BugFixPhaseResult(status=BugFixPhaseStatus.PASSED, evidence={"log": "complete"})

    phase_path = store.save_phase("test-red", first)
    assert store.save_phase("test-red", second) == phase_path

    assert json.loads(phase_path.read_text(encoding="utf-8")) == second.model_dump(mode="json")
    assert list(phase_path.parent.iterdir()) == [phase_path]


def test_evidence_store_saves_submission_manifest_diagnostic_and_final_result(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    store = EvidenceStore(paths)
    phase = BugFixPhaseResult(status=BugFixPhaseStatus.PASSED)

    patch_path = store.save_submission("generated-fix.patch", "diff --git a/a b/a\n")
    text_path = store.save_submission("agent-output.txt", "finished")
    manifest_path = store.save_checkpoint_manifest("baseline", {"sha256": "abc", "files": ["app.app"]})
    diagnostic_path = store.save_text("container.log", "diagnostic")
    result_path = store.save_final_result(phase)

    assert patch_path.read_text(encoding="utf-8") == "diff --git a/a b/a\n"
    assert text_path.read_text(encoding="utf-8") == "finished"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {"files": ["app.app"], "sha256": "abc"}
    assert diagnostic_path.read_text(encoding="utf-8") == "diagnostic"
    assert json.loads(result_path.read_text(encoding="utf-8")) == phase.model_dump(mode="json")


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("save_phase", ("../phase", BugFixPhaseResult())),
        ("save_phase", ("phase:stream", BugFixPhaseResult())),
        ("save_submission", ("../submission.patch", "patch")),
        ("save_checkpoint_manifest", ("../manifest", {})),
        ("save_text", ("../diagnostic.txt", "text")),
    ],
)
def test_evidence_names_reject_path_traversal(tmp_path: Path, method_name: str, arguments: tuple[object, ...]) -> None:
    store = EvidenceStore(_lifecycle_paths(tmp_path))

    with pytest.raises(ValueError, match="name"):
        getattr(store, method_name)(*arguments)


def test_protect_artifact_copies_reuses_and_rejects_tampering(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    store = EvidenceStore(paths)
    source = tmp_path / "checkpoint.zip"
    source.write_bytes(b"checkpoint")

    protected = store.protect_artifact(source, "checkpoints")

    assert protected == paths.final_results / "artifacts" / "checkpoints" / f"{sha256_file(source)}.zip"
    assert protected.read_bytes() == b"checkpoint"
    assert store.protect_artifact(source, "checkpoints") == protected

    protected.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        store.protect_artifact(source, "checkpoints")


@pytest.mark.parametrize("kind", ["../checkpoints", "nested/kind", r"nested\kind", "kind:stream", "C:", "", ".", ".."])
def test_protect_artifact_rejects_unsafe_kind(tmp_path: Path, kind: str) -> None:
    store = EvidenceStore(_lifecycle_paths(tmp_path))
    source = tmp_path / "artifact.app"
    source.write_bytes(b"artifact")

    with pytest.raises(ValueError, match="kind"):
        store.protect_artifact(source, kind)


def test_evidence_store_accepts_explicit_roots(tmp_path: Path) -> None:
    store = EvidenceStore(
        entry_root=tmp_path / "entry",
        evidence_root=tmp_path / "entry" / "evidence",
        protected_root=tmp_path / "protected",
        final_results=tmp_path / "protected" / "final-results",
    )

    assert store.save_text("run.log", "ok") == tmp_path / "entry" / "evidence" / "diagnostics" / "run.log"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("final_results", "entry"),
        ("final_results", "protected"),
        ("evidence", "protected"),
    ],
)
def test_evidence_store_rejects_roots_outside_trust_boundaries(tmp_path: Path, field: str, value: str) -> None:
    paths = _lifecycle_paths(tmp_path)
    replacements = {
        "entry": paths.entry_root / "exposed",
        "protected": paths.protected_root,
    }
    invalid = BugFixLifecyclePaths(**{**paths.__dict__, field: replacements[value]})

    with pytest.raises(ValueError, match=r"entry_root|protected_root"):
        EvidenceStore(invalid)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
def test_evidence_store_rechecks_junctions_before_writing(tmp_path: Path) -> None:
    paths = _lifecycle_paths(tmp_path)
    store = EvidenceStore(paths)
    _create_junction(paths.evidence, tmp_path / "outside")

    with pytest.raises(ValueError, match="reparse point"):
        store.save_text("run.log", "blocked")
