from pathlib import Path

from granite_storage import StorageManager, StoragePolicy
from granite_storage.backends.local import LocalStorageBackend
from granite_storage.gc import StorageGarbageCollector


def test_gc_detects_orphans(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    manager = StorageManager(
        backends={"local": backend},
        policies={
            "dummy_content": StoragePolicy(
                storage_key="dummy_content", backend_key="local", key_prefix="tests"
            )
        },
    )
    ref = backend.put_bytes(key="tests/model/aa/bb/id/file.txt", content=b"ok")
    ref.storage_key = "dummy_content"

    gc = StorageGarbageCollector(manager, iter_references=lambda: [])
    report = gc.collect(storage_key="dummy_content", dry_run=True)
    assert report.orphaned == 1
