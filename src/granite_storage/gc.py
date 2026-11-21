from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.manager import StorageManager
from granite_storage.models import StoredObjectRef

DEFAULT_MIN_AGE = timedelta(hours=24)


@dataclass
class GarbageCollectionReport:
    scanned: int = 0
    referenced: int = 0
    orphaned: int = 0
    deleted: int = 0
    skipped_recent: int = 0
    errors: list[str] = field(default_factory=list)


class StorageGarbageCollector:
    """Find and delete objects that no reference points to.

    Safeguards (data loss here is irreversible):

    * only objects older than ``min_age`` are deleted, so an upload whose
      database transaction has not committed yet is never collected;
      objects whose age is unknown are treated as recent;
    * the policy must define ``key_prefix`` (otherwise the whole backend would
      be scanned) unless ``allow_unscoped=True``;
    * ``iter_references`` must yield the references of EVERY model that uses
      the policy; if it yields none while objects exist, a real run aborts
      unless ``force=True``;
    * a failure deleting one object is recorded in ``report.errors`` and
      does not abort the run.
    """

    def __init__(
        self,
        manager: StorageManager,
        iter_references: Callable[[], Iterable[StoredObjectRef | None]],
        *,
        min_age: timedelta = DEFAULT_MIN_AGE,
        allow_unscoped: bool = False,
    ):
        self.manager = manager
        self.iter_references = iter_references
        self.min_age = min_age
        self.allow_unscoped = allow_unscoped

    def _is_too_recent(
        self,
        backend: StorageBackend,
        location: str,
        report: GarbageCollectionReport,
    ) -> bool:
        """True if *location* must not be deleted yet (or its age is unknown)."""
        if self.min_age <= timedelta(0):
            return False
        last_modified = getattr(backend, "last_modified", None)
        try:
            modified = last_modified(location) if last_modified else None
        except StorageError as exc:
            report.errors.append(f"{location}: {exc}")
            return True
        if modified is None or datetime.now(UTC) - modified < self.min_age:
            report.skipped_recent += 1
            return True
        return False

    @staticmethod
    def _delete(
        backend: StorageBackend,
        storage_key: str,
        location: str,
        report: GarbageCollectionReport,
    ) -> None:
        try:
            backend.delete(
                StoredObjectRef(
                    storage_key=storage_key,
                    backend=backend.backend_name,
                    location=location,
                    size=0,
                    checksum="",
                )
            )
        except StorageError as exc:
            report.errors.append(f"{location}: {exc}")
        else:
            report.deleted += 1

    def _referenced_locations(
        self, storage_key: str, report: GarbageCollectionReport
    ) -> set[str]:
        locations: set[str] = set()
        for ref in self.iter_references():
            if ref and ref.storage_key == storage_key:
                locations.add(ref.location)
                report.referenced += 1
        return locations

    def collect(
        self,
        *,
        storage_key: str,
        dry_run: bool = True,
        force: bool = False,
    ) -> GarbageCollectionReport:
        policy = self.manager.get_policy(storage_key)
        backend = self.manager.get_backend_for_policy(policy)
        prefixes = policy.read_prefixes
        if not prefixes and not self.allow_unscoped:
            raise StorageError(
                f"Policy '{storage_key}' has no key_prefix: refusing to scan the "
                "whole backend (set allow_unscoped=True to override)."
            )
        report = GarbageCollectionReport()
        referenced_locations = self._referenced_locations(storage_key, report)

        orphans: list[str] = []
        for prefix in prefixes or (None,):
            for location in backend.iter_locations(prefix=prefix):
                report.scanned += 1
                if location not in referenced_locations:
                    orphans.append(location)
        report.orphaned = len(orphans)

        if not dry_run and not force and report.scanned > 0 and report.referenced == 0:
            raise StorageError(
                f"No references found for '{storage_key}' but {report.scanned} "
                "objects exist: refusing to delete everything "
                "(check iter_references, or pass force=True)."
            )

        for location in orphans:
            if self._is_too_recent(backend, location, report):
                continue
            if not dry_run:
                self._delete(backend, storage_key, location, report)

        return report
