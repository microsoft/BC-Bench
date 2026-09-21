from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore
from bcbench.evaluate.bugfix_lifecycle.models import AppInventoryEntry
from bcbench.exceptions import PackageInventoryError

InventoryReader = Callable[[], Sequence[AppInventoryEntry]]


class InventoryVerifier:
    def __init__(self, reader: InventoryReader, evidence_store: EvidenceStore) -> None:
        if reader is None:
            raise ValueError("An inventory reader is required")
        if evidence_store is None:
            raise ValueError("An evidence store is required")
        self._reader = getattr(reader, "read", reader)
        self._evidence_store = evidence_store
        self.last_evidence_path: Path | None = None

    def verify(
        self,
        name: str,
        expected: Sequence[AppInventoryEntry],
    ) -> tuple[tuple[AppInventoryEntry, ...], Path]:
        self.last_evidence_path = None
        expected_inventory = _normalized_inventory(expected)
        try:
            actual_inventory = _normalized_inventory(self._reader())
        except (OSError, TypeError, ValueError) as error:
            raise PackageInventoryError(f"Failed to read installed application inventory: {error}") from error

        try:
            self.last_evidence_path = self._evidence_store.save_inventory(
                name,
                [app.to_dict() for app in expected_inventory],
                [app.to_dict() for app in actual_inventory],
            )
        except (OSError, TypeError, ValueError) as error:
            raise PackageInventoryError(f"Failed to persist application inventory evidence: {error}") from error
        unhealthy = sorted(app.name for app in actual_inventory if not app.installed or not app.synchronized)
        if unhealthy:
            raise PackageInventoryError(f"Applications are not installed and synchronized: {unhealthy}")
        _require_unique_identities(expected_inventory, "expected")
        _require_unique_identities(actual_inventory, "actual")
        _require_unique_hash_identities(expected_inventory, "expected")
        _require_unique_hash_identities(actual_inventory, "actual")
        _require_consistent_hash_identities(expected_inventory, actual_inventory)

        expected_counter = Counter(expected_inventory)
        actual_counter = Counter(actual_inventory)
        if actual_counter != expected_counter:
            missing = _expanded_difference(expected_counter - actual_counter)
            unexpected = _expanded_difference(actual_counter - expected_counter)
            raise PackageInventoryError(
                f"Installed application inventory mismatch: missing={missing}, unexpected={unexpected}. Nullable package_id and content_hash fields only match when both values are null."
            )

        if self.last_evidence_path is None:
            raise PackageInventoryError("Application inventory evidence was not persisted")
        return actual_inventory, self.last_evidence_path


def expected_inventory_after_publication(
    baseline: Sequence[AppInventoryEntry],
    published: Sequence[AppInventoryEntry],
) -> tuple[AppInventoryEntry, ...]:
    published_inventory = _normalized_inventory(published)
    _require_unique_identities(published_inventory, "published")
    published_ids = Counter(app.app_id for app in published_inventory)
    duplicate_ids = sorted(app_id for app_id, count in published_ids.items() if count > 1)
    if duplicate_ids:
        raise PackageInventoryError(f"Publication returned duplicate application IDs: {duplicate_ids}")

    remaining = tuple(app for app in baseline if app.app_id not in published_ids)
    return _normalized_inventory((*remaining, *published_inventory))


def _normalized_inventory(apps: Sequence[AppInventoryEntry]) -> tuple[AppInventoryEntry, ...]:
    return tuple(
        sorted(
            apps,
            key=lambda app: (
                app.app_id,
                app.name,
                app.publisher,
                app.version,
                (0, "") if app.package_id is None else (1, app.package_id),
                app.scope,
                app.installed,
                app.synchronized,
                (0, "") if app.content_hash is None else (1, app.content_hash),
            ),
        )
    )


def _identity(app: AppInventoryEntry) -> tuple[str, ...]:
    return (
        app.app_id,
        app.name,
        app.publisher,
        app.version,
        "<null>" if app.package_id is None else app.package_id,
        app.scope,
    )


def _require_unique_identities(apps: Sequence[AppInventoryEntry], label: str) -> None:
    identities = Counter(_identity(app) for app in apps)
    duplicates = sorted(identity for identity, count in identities.items() if count > 1)
    if duplicates:
        raise PackageInventoryError(f"{label.capitalize()} application inventory contains duplicate identities: {duplicates}")


def _require_consistent_hash_identities(
    expected: Sequence[AppInventoryEntry],
    actual: Sequence[AppInventoryEntry],
) -> None:
    expected_by_hash = {app.content_hash: _identity(app) for app in expected if app.content_hash is not None}
    conflicts = sorted(
        (
            app.content_hash,
            expected_by_hash[app.content_hash],
            _identity(app),
        )
        for app in actual
        if app.content_hash is not None and app.content_hash in expected_by_hash and expected_by_hash[app.content_hash] != _identity(app)
    )
    if conflicts:
        raise PackageInventoryError(f"Application inventory reuses a content hash with a different identity: {conflicts}")


def _require_unique_hash_identities(
    apps: Sequence[AppInventoryEntry],
    label: str,
) -> None:
    identities_by_hash: dict[str, set[tuple[str, ...]]] = {}
    for app in apps:
        if app.content_hash is not None:
            identities_by_hash.setdefault(app.content_hash, set()).add(_identity(app))
    conflicts = sorted((content_hash, sorted(identities)) for content_hash, identities in identities_by_hash.items() if len(identities) > 1)
    if conflicts:
        raise PackageInventoryError(f"{label.capitalize()} application inventory reuses content hashes across different identities: {conflicts}")


def _expanded_difference(counter: Counter[AppInventoryEntry]) -> list[dict[str, object]]:
    return [app.to_dict() for app, count in sorted(counter.items(), key=lambda item: repr(item[0])) for _ in range(count)]
