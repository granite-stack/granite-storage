from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from granite_storage.manager import StorageManager
from granite_storage.models import StoredObjectRef


@dataclass
class GarbageCollectionReport:
    scanned: int = 0
    referenced: int = 0
    orphaned: int = 0
    deleted: int = 0


class StorageGarbageCollector:
    def __init__(
        self,
        manager: StorageManager,
        iter_references: Callable[[], Iterable[StoredObjectRef | None]],
    ):
        self.manager = manager
        self.iter_references = iter_references

    def collect(
        self, *, storage_key: str, dry_run: bool = True
    ) -> GarbageCollectionReport:
        policy = self.manager.get_policy(storage_key)
        backend = self.manager.get_backend_for_policy(policy)
        report = GarbageCollectionReport()
        referenced_locations: set[str] = set()

        for ref in self.iter_references():
            if ref and ref.storage_key == storage_key:
                referenced_locations.add(ref.location)
                report.referenced += 1

        for location in backend.iter_locations(prefix=policy.key_prefix):
            report.scanned += 1
            if location in referenced_locations:
                continue
            report.orphaned += 1
            if not dry_run:
                backend.delete(
                    StoredObjectRef(
                        storage_key=storage_key,
                        backend=backend.backend_name,
                        location=location,
                        size=0,
                        checksum="",
                    )
                )
                report.deleted += 1

        return report
