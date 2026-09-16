import json
import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from bcbench.evaluate.bugfix_lifecycle.models import BugFixLifecyclePaths
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
    with suppress(OSError):
        os.fsync(file.fileno())


class EvidenceStore:
    def __init__(
        self,
        paths: BugFixLifecyclePaths | Path | None = None,
        protected_root: Path | None = None,
        *,
        evidence_root: Path | None = None,
    ) -> None:
        if isinstance(paths, BugFixLifecyclePaths):
            if evidence_root is not None or protected_root is not None:
                raise ValueError("Explicit roots cannot be combined with lifecycle paths")
            self._evidence_root = paths.evidence
            self._protected_root = paths.final_results
        else:
            if isinstance(paths, Path):
                if evidence_root is not None:
                    raise ValueError("Evidence root was provided twice")
                evidence_root = paths
            if evidence_root is None or protected_root is None:
                raise ValueError("Evidence and protected roots are required")
            self._evidence_root = evidence_root
            self._protected_root = protected_root

    def save_phase(self, name: str, result: BugFixPhaseResult) -> Path:
        return self._write_json(self._evidence_root / "phases" / _with_suffix(name, ".json"), result)

    def save_submission(self, name: str, content: str) -> Path:
        return self._write_text(self._evidence_root / "submissions" / _safe_name(name), content)

    def save_checkpoint_manifest(self, name: str, manifest: object) -> Path:
        return self._write_json(self._evidence_root / "checkpoints" / _with_suffix(name, ".json"), manifest)

    def save_text(self, name: str, diagnostic: str) -> Path:
        return self._write_text(self._evidence_root / "diagnostics" / _safe_name(name), diagnostic)

    def save_final_result(self, result: object) -> Path:
        return self._write_json(self._protected_root / "final-result.json", result)

    def protect_artifact(self, source: Path, kind: str) -> Path:
        safe_kind = _safe_kind(kind)
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Artifact source must be a regular file: {source}")

        source_hash = sha256_file(source)
        destination = self._protected_root / "artifacts" / safe_kind / f"{source_hash}{source.suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not destination.is_file() or destination.is_symlink() or sha256_file(destination) != source_hash:
                raise ValueError(f"Protected artifact hash mismatch: {destination}")
            return destination

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                with source.open("rb") as source_file:
                    shutil.copyfileobj(source_file, temporary)
                _flush_file(temporary)

            if sha256_file(temporary_path) != source_hash:
                raise ValueError(f"Copied artifact hash mismatch: {source}")
            if destination.exists():
                if sha256_file(destination) != source_hash:
                    raise ValueError(f"Protected artifact hash mismatch: {destination}")
                temporary_path.unlink()
                return destination
            temporary_path.replace(destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        if sha256_file(destination) != source_hash:
            raise ValueError(f"Protected artifact hash mismatch after replace: {destination}")
        return destination

    def _write_json(self, destination: Path, value: object) -> Path:
        serialized = json.dumps(_json_serializable(value), indent=2, sort_keys=True) + "\n"
        return self._write_text(destination, serialized)

    def _write_text(self, destination: Path, content: str) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
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
                temporary.write(content)
                _flush_file(temporary)
            temporary_path.replace(destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return destination
