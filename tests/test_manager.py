"""Tests for StorageManager and SizeLimitedStream."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import ContentTooLargeError, StorageError
from granite_storage.manager import SizeLimitedStream, StorageManager
from granite_storage.policies import StoragePolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path, max_size: int | None = None) -> StorageManager:
    return StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={
            "docs": StoragePolicy(
                storage_key="docs",
                backend_key="local",
                max_size=max_size,
                key_prefix="docs",
            )
        },
    )


# ---------------------------------------------------------------------------
# StorageManager – error paths
# ---------------------------------------------------------------------------

def test_get_policy_unknown_raises(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    with pytest.raises(StorageError, match="Unknown storage policy"):
        manager.get_policy("nonexistent")


def test_get_backend_for_policy_unknown_raises(tmp_path: Path) -> None:
    manager = StorageManager(
        backends={},
        policies={
            "docs": StoragePolicy(storage_key="docs", backend_key="missing_backend")
        },
    )
    policy = manager.get_policy("docs")
    with pytest.raises(StorageError, match="Unknown backend"):
        manager.get_backend_for_policy(policy)


def test_put_bytes_exceeds_max_size_raises(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, max_size=4)
    with pytest.raises(ContentTooLargeError):
        manager.put_bytes(
            storage_key="docs",
            model_name="Article",
            entity_id=1,
            field_name="body",
            content=b"12345",
        )


# ---------------------------------------------------------------------------
# StorageManager – happy paths
# ---------------------------------------------------------------------------

def test_put_bytes_and_get(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    ref = manager.put_bytes(
        storage_key="docs",
        model_name="Article",
        entity_id=42,
        field_name="body",
        content=b"hello world",
        content_type="text/plain",
        original_filename="body.txt",
    )
    assert manager.get(ref) == b"hello world"


def test_put_stream_and_open(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    ref = manager.put_stream(
        storage_key="docs",
        model_name="Article",
        entity_id=7,
        field_name="body",
        stream=io.BytesIO(b"stream content"),
        content_type="text/plain",
    )
    with manager.open(ref) as f:
        data = f.read()
    assert data == b"stream content"


def test_delete_and_exists(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    ref = manager.put_bytes(
        storage_key="docs",
        model_name="Article",
        entity_id=99,
        field_name="body",
        content=b"data",
    )
    assert manager.exists(ref)
    manager.delete(ref)
    assert not manager.exists(ref)


def test_build_location_with_key_prefix(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    ref = manager.put_bytes(
        storage_key="docs",
        model_name="Report",
        entity_id="abc",
        field_name="attachment",
        content=b"x",
        original_filename="report.pdf",
    )
    assert "docs" in ref.location


def test_put_bytes_no_prefix(tmp_path: Path) -> None:
    manager = StorageManager(
        backends={"local": LocalStorageBackend(tmp_path)},
        policies={
            "bare": StoragePolicy(storage_key="bare", backend_key="local")
        },
    )
    ref = manager.put_bytes(
        storage_key="bare",
        model_name="Obj",
        entity_id=1,
        field_name="data",
        content=b"no prefix",
    )
    assert manager.get(ref) == b"no prefix"


# ---------------------------------------------------------------------------
# SizeLimitedStream
# ---------------------------------------------------------------------------

def test_size_limited_stream_within_limit() -> None:
    stream = SizeLimitedStream(io.BytesIO(b"hello"), max_size=100)
    assert stream.read() == b"hello"


def test_size_limited_stream_exceeds_limit() -> None:
    stream = SizeLimitedStream(io.BytesIO(b"hello world"), max_size=5)
    with pytest.raises(ContentTooLargeError):
        stream.read()


def test_size_limited_stream_no_limit() -> None:
    stream = SizeLimitedStream(io.BytesIO(b"x" * 10_000), max_size=None)
    data = stream.read()
    assert len(data) == 10_000


def test_size_limited_stream_write_raises() -> None:
    stream = SizeLimitedStream(io.BytesIO(), max_size=None)
    with pytest.raises(io.UnsupportedOperation):
        stream.write(b"x")


def test_size_limited_stream_writelines_raises() -> None:
    stream = SizeLimitedStream(io.BytesIO(), max_size=None)
    with pytest.raises(io.UnsupportedOperation):
        stream.writelines([b"x"])


def test_size_limited_stream_iteration() -> None:
    stream = SizeLimitedStream(io.BytesIO(b"abcdef"), max_size=None, chunk_size=2)
    chunks = list(stream)
    assert b"".join(chunks) == b"abcdef"


def test_size_limited_stream_context_manager() -> None:
    inner = io.BytesIO(b"ctx")
    with SizeLimitedStream(inner, max_size=None) as s:
        data = s.read()
    assert data == b"ctx"


def test_size_limited_stream_readable() -> None:
    stream = SizeLimitedStream(io.BytesIO(b""), max_size=None)
    assert stream.readable()
    assert not stream.writable()
