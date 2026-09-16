import json
import os
import shutil
import tempfile
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from bcbench.evaluate.bugfix_lifecycle.models import BugFixLifecyclePaths
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    absolute_path,
    reject_reparse_components,
    require_strict_descendant,
    validate_evidence_roots,
    validate_lifecycle_paths,
)
from bcbench.results.bugfix import BugFixPhaseResult

_HASH_CHUNK_SIZE = 1024 * 1024
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class _FlushableFile(Protocol):
    def flush(self) -> None: ...

    def fileno(self) -> int: ...


def _json_serializable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _safe_component(value: str, label: str) -> str:
    reserved_stem = value.partition(".")[0].upper()
    if not value or value in {".", ".."} or value.endswith((" ", ".")) or any(character in value for character in ("/", "\\", ":", "\0")) or reserved_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _safe_name(name: str) -> str:
    return _safe_component(name, "evidence name")


def _safe_kind(kind: str) -> str:
    return _safe_component(kind, "artifact kind")


def _with_suffix(name: str, suffix: str) -> str:
    safe_name = _safe_name(name)
    return safe_name if safe_name.endswith(suffix) else f"{safe_name}{suffix}"


def _flush_file(file: _FlushableFile) -> None:
    file.flush()
    os.fsync(file.fileno())


class EvidenceStore:
    def __init__(
        self,
        paths: BugFixLifecyclePaths | Path | None = None,
        *,
        entry_root: Path | None = None,
        evidence_root: Path | None = None,
        protected_root: Path | None = None,
        final_results: Path | None = None,
    ) -> None:
        if isinstance(paths, BugFixLifecyclePaths):
            if any(root is not None for root in (entry_root, evidence_root, protected_root, final_results)):
                raise ValueError("Explicit roots cannot be combined with lifecycle paths")
            validated_paths = validate_lifecycle_paths(paths)
            self._entry_root = validated_paths.entry_root
            self._evidence_root = validated_paths.evidence
            self._protected_root = validated_paths.protected_root
            self._final_results = validated_paths.final_results
        elif isinstance(paths, Path):
            if any(root is not None for root in (entry_root, evidence_root, protected_root, final_results)):
                raise ValueError("Explicit roots cannot be combined with a convenience root")
            self._entry_root, self._evidence_root, self._protected_root, self._final_results = validate_evidence_roots(
                paths / "entry",
                paths / "entry" / "evidence",
                paths / "protected",
                paths / "protected" / "final-results",
            )
        else:
            if paths is not None:
                raise TypeError("paths must be BugFixLifecyclePaths or Path")
            if entry_root is None or evidence_root is None or protected_root is None or final_results is None:
                raise ValueError("Entry, evidence, protected, and final result roots are required")
            self._entry_root, self._evidence_root, self._protected_root, self._final_results = validate_evidence_roots(
                entry_root,
                evidence_root,
                protected_root,
                final_results,
            )

    def save_phase(self, name: str, result: BugFixPhaseResult) -> Path:
        return self._write_json(self._evidence_root / "phases" / _with_suffix(name, ".json"), result, self._evidence_root, self._entry_root)

    def save_submission(self, name: str, content: str) -> Path:
        return self._write_text(self._evidence_root / "submissions" / _safe_name(name), content, self._evidence_root, self._entry_root)

    def save_checkpoint_manifest(self, name: str, manifest: object) -> Path:
        return self._write_json(
            self._evidence_root / "checkpoints" / _with_suffix(name, ".json"),
            manifest,
            self._evidence_root,
            self._entry_root,
        )

    def save_text(self, name: str, diagnostic: str) -> Path:
        return self._write_text(self._evidence_root / "diagnostics" / _safe_name(name), diagnostic, self._evidence_root, self._entry_root)

    def save_final_result(self, result: object) -> Path:
        return self._write_json(self._final_results / "final-result.json", result, self._final_results, self._protected_root)

    def protect_artifact(self, source: Path, kind: str) -> Path:
        safe_kind = _safe_kind(kind)
        self._validate_destination(self._final_results, self._final_results, self._protected_root)
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Artifact source must be a regular file: {source}")

        source_hash = sha256_file(source)
        destination = self._final_results / "artifacts" / safe_kind / f"{source_hash}{source.suffix}"
        self._validate_destination(destination, self._final_results, self._protected_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._validate_destination(destination, self._final_results, self._protected_root)
        if destination.exists():
            if not destination.is_file() or destination.is_symlink() or sha256_file(destination) != source_hash:
                raise ValueError(f"Protected artifact hash mismatch: {destination}")
            return destination

        temporary_path: Path | None = None
        try:
            self._validate_destination(destination, self._final_results, self._protected_root)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                self._validate_destination(temporary_path, self._final_results, self._protected_root)
                if not source.is_file() or source.is_symlink():
                    raise ValueError(f"Artifact source must be a regular file: {source}")
                with source.open("rb") as source_file:
                    shutil.copyfileobj(source_file, temporary)
                _flush_file(temporary)

            self._validate_destination(destination, self._final_results, self._protected_root)
            if sha256_file(temporary_path) != source_hash:
                raise ValueError(f"Copied artifact hash mismatch: {source}")
            if destination.exists():
                if sha256_file(destination) != source_hash:
                    raise ValueError(f"Protected artifact hash mismatch: {destination}")
                temporary_path.unlink()
                return destination
            self._validate_destination(destination, self._final_results, self._protected_root)
            temporary_path.replace(destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        if sha256_file(destination) != source_hash:
            raise ValueError(f"Protected artifact hash mismatch after replace: {destination}")
        return destination

    def _validate_roots(self) -> None:
        validate_evidence_roots(self._entry_root, self._evidence_root, self._protected_root, self._final_results)

    def _validate_destination(self, destination: Path, managed_root: Path, containing_root: Path) -> Path:
        self._validate_roots()
        absolute_destination = absolute_path(destination)
        if absolute_destination != managed_root:
            require_strict_descendant(absolute_destination, managed_root, "destination", managed_root.name)
        reject_reparse_components(absolute_destination, containing_root)
        return absolute_destination

    def _write_json(self, destination: Path, value: object, managed_root: Path, containing_root: Path) -> Path:
        serialized = json.dumps(_json_serializable(value), indent=2, sort_keys=True) + "\n"
        return self._write_text(destination, serialized, managed_root, containing_root)

    def _write_text(self, destination: Path, content: str, managed_root: Path, containing_root: Path) -> Path:
        destination = self._validate_destination(destination, managed_root, containing_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._validate_destination(destination, managed_root, containing_root)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                self._validate_destination(temporary_path, managed_root, containing_root)
                temporary.write(content)
                _flush_file(temporary)
            self._validate_destination(destination, managed_root, containing_root)
            temporary_path.replace(destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return destination
