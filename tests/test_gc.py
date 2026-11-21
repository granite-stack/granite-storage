from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from granite_storage import StorageManager, StoragePolicy, StoredObjectRef
from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.gc import StorageGarbageCollector

OLD = time.time() - 7 * 24 * 3600


def _setup(tmp_path: Path, **policy_kwargs):
    backend = LocalStorageBackend(tmp_path)
    kwargs = {"key_prefix": "tests", **policy_kwargs}
    manager = StorageManager(
        backends={"local": backend},
        policies={
            "dummy_content": StoragePolicy(
                storage_key="dummy_content", backend_key="local", **kwargs
            )
        },
    )
    return backend, manager


def _put(
    backend: LocalStorageBackend, key: str, *, old: bool = True
) -> StoredObjectRef:
    ref = backend.put_bytes(key=key, content=b"ok")
    ref.storage_key = "dummy_content"
    if old:
        os.utime(backend.root_dir / key, (OLD, OLD))
    return ref


def test_gc_detects_orphans(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    _put(backend, "tests/model/aa/bb/id/file.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [])
    report = gc.collect(storage_key="dummy_content", dry_run=True)
    assert report.orphaned == 1
    assert (tmp_path / "tests/model/aa/bb/id/file.txt").exists()


def test_gc_really_deletes_old_orphans_and_keeps_referenced(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    keep = _put(backend, "tests/m/keep.txt")
    _put(backend, "tests/m/orphan.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [keep, None])
    report = gc.collect(storage_key="dummy_content", dry_run=False)
    assert (report.scanned, report.referenced, report.orphaned, report.deleted) == (
        2,
        1,
        1,
        1,
    )
    assert (tmp_path / "tests/m/keep.txt").exists()
    assert not (tmp_path / "tests/m/orphan.txt").exists()


def test_gc_grace_period_protects_uncommitted_uploads(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    keep = _put(backend, "tests/m/keep.txt")
    _put(backend, "tests/m/fresh.txt", old=False)  # uploaded, not committed yet
    gc = StorageGarbageCollector(manager, iter_references=lambda: [keep])
    report = gc.collect(storage_key="dummy_content", dry_run=False)
    assert report.orphaned == 1
    assert report.skipped_recent == 1
    assert report.deleted == 0
    assert (tmp_path / "tests/m/fresh.txt").exists()
    # with no grace period it is collected
    gc0 = StorageGarbageCollector(
        manager, iter_references=lambda: [keep], min_age=timedelta(0)
    )
    assert gc0.collect(storage_key="dummy_content", dry_run=False).deleted == 1


def test_gc_requires_key_prefix(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path, key_prefix=None)
    _put(backend, "other/policy/file.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [])
    with pytest.raises(StorageError, match="key_prefix"):
        gc.collect(storage_key="dummy_content", dry_run=False)
    assert (tmp_path / "other/policy/file.txt").exists()
    unscoped = StorageGarbageCollector(
        manager, iter_references=lambda: [], allow_unscoped=True
    )
    assert unscoped.collect(storage_key="dummy_content").orphaned == 1


def test_gc_does_not_touch_sibling_prefix(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    _put(backend, "tests2/m/other-policy.txt")
    keep = _put(backend, "tests/m/keep.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [keep])
    gc.collect(storage_key="dummy_content", dry_run=False)
    assert (tmp_path / "tests2/m/other-policy.txt").exists()


def test_gc_aborts_when_no_references_but_objects_exist(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    _put(backend, "tests/m/a.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [])
    with pytest.raises(StorageError, match="refusing"):
        gc.collect(storage_key="dummy_content", dry_run=False)
    assert (tmp_path / "tests/m/a.txt").exists()
    assert (
        gc.collect(storage_key="dummy_content", dry_run=False, force=True).deleted == 1
    )


def test_gc_failing_iter_references_deletes_nothing(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    _put(backend, "tests/m/a.txt")

    def boom():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    gc = StorageGarbageCollector(manager, iter_references=boom)
    with pytest.raises(RuntimeError):
        gc.collect(storage_key="dummy_content", dry_run=False)
    assert (tmp_path / "tests/m/a.txt").exists()


def test_gc_continues_after_a_delete_error(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path)
    keep = _put(backend, "tests/m/keep.txt")
    _put(backend, "tests/m/a.txt")
    _put(backend, "tests/m/b.txt")
    real_delete = backend.delete

    def flaky(ref: StoredObjectRef) -> None:
        if ref.location.endswith("a.txt"):
            raise StorageError("boom")
        real_delete(ref)

    backend.delete = flaky  # type: ignore[method-assign]
    gc = StorageGarbageCollector(manager, iter_references=lambda: [keep])
    report = gc.collect(storage_key="dummy_content", dry_run=False)
    assert report.deleted == 1
    assert len(report.errors) == 1 and "a.txt" in report.errors[0]
    assert not (tmp_path / "tests/m/b.txt").exists()


def test_gc_scans_legacy_prefixes(tmp_path: Path) -> None:
    backend, manager = _setup(tmp_path, legacy_key_prefixes=("old",))
    keep = _put(backend, "old/m/keep.txt")
    _put(backend, "old/m/orphan.txt")
    gc = StorageGarbageCollector(manager, iter_references=lambda: [keep])
    report = gc.collect(storage_key="dummy_content", dry_run=False)
    assert report.deleted == 1
    assert (tmp_path / "old/m/keep.txt").exists()


def test_gc_on_s3_deletes_only_old_orphans_in_prefix() -> None:
    import boto3
    from moto import mock_aws

    from granite_storage.backends.s3 import S3StorageBackend

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="gc-bucket")
        backend = S3StorageBackend(bucket="gc-bucket", client=client)
        manager = StorageManager(
            backends={"s3": backend},
            policies={"p": StoragePolicy("p", "s3", key_prefix="docs")},
        )
        keep = backend.put_bytes(key="docs/keep.txt", content=b"1")
        keep.storage_key = "p"
        backend.put_bytes(key="docs/orphan.txt", content=b"1")
        backend.put_bytes(key="docs2/sibling.txt", content=b"1")
        gc = StorageGarbageCollector(
            manager, iter_references=lambda: [keep], min_age=timedelta(0)
        )
        report = gc.collect(storage_key="p", dry_run=False)
        assert report.deleted == 1
        assert sorted(backend.iter_locations()) == [
            "docs/keep.txt",
            "docs2/sibling.txt",
        ]
