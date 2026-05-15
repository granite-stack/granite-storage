"""Additional tests for LocalStorageBackend covering uncovered paths."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef


def _make_ref(location: str) -> StoredObjectRef:
    return StoredObjectRef(
        storage_key="",
        backend="local",
        location=location,
        size=0,
        checksum="",
    )


def test_put_bytes_with_content_type_and_extra(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    ref = backend.put_bytes(
        key="dir/file.txt",
        content=b"hello",
        content_type="text/plain",
        original_filename="file.txt",
        extra={"tag": "test"},
    )
    assert ref.content_type == "text/plain"
    assert ref.original_filename == "file.txt"
    assert ref.extra == {"tag": "test"}
    assert ref.size == 5


def test_put_stream_with_explicit_checksum_and_size(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    ref = backend.put_stream(
        key="dir/file.bin",
        stream=io.BytesIO(b"data"),
        size=4,
        checksum="md5:abc",
        content_type="application/octet-stream",
        original_filename="file.bin",
        extra={"env": "test"},
    )
    assert ref.size == 4
    assert ref.checksum == "md5:abc"
    assert ref.content_type == "application/octet-stream"


def test_open_returns_readable_stream(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="open_test.txt", content=b"stream content")
    ref = _make_ref("open_test.txt")
    with backend.open(ref) as f:
        data = f.read()
    assert data == b"stream content"


def test_open_raises_if_not_found(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    ref = _make_ref("nonexistent.txt")
    with pytest.raises(StorageError, match="not found"):
        backend.open(ref)


def test_get_raises_if_not_found(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    ref = _make_ref("ghost.txt")
    with pytest.raises(StorageError, match="not found"):
        backend.get(ref)


def test_delete_is_idempotent(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    ref = _make_ref("missing.txt")
    # Should not raise even if file does not exist
    backend.delete(ref)


def test_delete_removes_existing_file(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="to_delete.txt", content=b"bye")
    ref = _make_ref("to_delete.txt")
    assert backend.exists(ref)
    backend.delete(ref)
    assert not backend.exists(ref)


def test_exists_false_for_missing_file(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    assert not backend.exists(_make_ref("nope.txt"))


def test_iter_locations_no_prefix(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="a/b.txt", content=b"x")
    backend.put_bytes(key="c.txt", content=b"y")
    locations = set(backend.iter_locations())
    assert "a/b.txt" in locations
    assert "c.txt" in locations


def test_iter_locations_with_prefix(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="sub/file.txt", content=b"z")
    backend.put_bytes(key="other.txt", content=b"w")
    locations = list(backend.iter_locations(prefix="sub"))
    assert any("file.txt" in loc for loc in locations)


def test_iter_locations_empty_prefix_not_exists(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    # Prefix path doesn't exist — should return empty without error
    locations = list(backend.iter_locations(prefix="nonexistent_prefix"))
    assert locations == []


def test_resolve_path_traversal_raises(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(StorageError, match="Invalid local storage path"):
        backend._resolve_path("../../etc/passwd")
