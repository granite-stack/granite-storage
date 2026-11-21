"""Stream semantics, atomic local writes, non-blocking upload."""

from __future__ import annotations

import asyncio
import io
import os
import stat
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from granite_storage import (
    StorageManager,
    StoragePolicy,
    StoredContentMixin,
    StoredObjectRef,
    StoredObjectRefType,
)
from granite_storage.backends.local import LocalStorageBackend
from granite_storage.exceptions import ContentTooLargeError, StorageError
from granite_storage.manager import SizeLimitedStream


def _manager(tmp_path: Path, max_size: int | None = None) -> StorageManager:
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


# GS-002 ---------------------------------------------------------------------


def test_put_stream_does_not_close_callers_stream(tmp_path: Path) -> None:
    src = io.BytesIO(b"hello")
    _manager(tmp_path).put_stream(
        storage_key="docs", model_name="m", entity_id="e", field_name="f", stream=src
    )
    assert not src.closed


def test_size_limited_stream_close_and_gc_keep_inner_open() -> None:
    inner = io.BytesIO(b"abc")
    wrapper = SizeLimitedStream(inner, max_size=None)
    wrapper.close()
    assert not inner.closed
    wrapper2 = SizeLimitedStream(inner, max_size=None)
    del wrapper2
    assert not inner.closed


# GS-005 ---------------------------------------------------------------------


@pytest.mark.parametrize("size", [-1, None])
def test_read_all_returns_everything(size) -> None:
    data = os.urandom(3_000_000)
    stream = SizeLimitedStream(io.BytesIO(data), max_size=None)
    assert stream.read(size) == data


def test_read_all_enforces_limit() -> None:
    stream = SizeLimitedStream(io.BytesIO(b"x" * 3_000_000), max_size=2_000_000)
    with pytest.raises(ContentTooLargeError):
        stream.read()


def test_readline_readlines_readinto_are_counted() -> None:
    with pytest.raises(ContentTooLargeError):
        SizeLimitedStream(io.BytesIO(b"aaaa\nbbbb\n"), max_size=6).readlines()
    with pytest.raises(ContentTooLargeError):
        s = SizeLimitedStream(io.BytesIO(b"aaaa\nbbbb\n"), max_size=6)
        s.readline()
        s.readline()
    s = SizeLimitedStream(io.BytesIO(b"x" * 10), max_size=5)
    with pytest.raises(ContentTooLargeError):
        s.readinto(bytearray(10))
    ok = SizeLimitedStream(io.BytesIO(b"abcdef"), max_size=None)
    buf = bytearray(4)
    assert ok.readinto(buf) == 4 and bytes(buf) == b"abcd"


def test_size_limited_stream_not_seekable() -> None:
    s = SizeLimitedStream(io.BytesIO(b"abc"), max_size=1)
    assert not s.seekable()
    with pytest.raises(io.UnsupportedOperation):
        s.seek(0)


# GS-004 / GS-015 / GS-016 -----------------------------------------------------


class _Boom(io.RawIOBase):
    def __init__(self) -> None:
        self.sent = False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if not self.sent:
            self.sent = True
            return b"partial"
        raise OSError("connection reset")


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_oversized_stream_leaves_no_file(tmp_path: Path) -> None:
    manager = _manager(tmp_path, max_size=5)
    with pytest.raises(ContentTooLargeError):
        manager.put_stream(
            storage_key="docs",
            model_name="m",
            entity_id="e",
            field_name="f",
            stream=io.BytesIO(b"0123456789"),
        )
    assert _files(tmp_path) == []


def test_failed_stream_keeps_previous_object_intact(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="a/b.txt", content=b"original")
    with pytest.raises(StorageError):
        backend.put_stream(key="a/b.txt", stream=_Boom())  # type: ignore[arg-type]
    ref = StoredObjectRef("", "local", "a/b.txt", 0, "")
    assert backend.get(ref) == b"original"
    assert [p.name for p in _files(tmp_path)] == ["b.txt"]


def test_declared_size_and_checksum_are_verified(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(StorageError):
        backend.put_stream(key="a.txt", stream=io.BytesIO(b"abc"), size=99)
    with pytest.raises(StorageError):
        backend.put_stream(key="a.txt", stream=io.BytesIO(b"abc"), checksum="sha256:0")
    assert _files(tmp_path) == []
    ref = backend.put_stream(key="a.txt", stream=io.BytesIO(b"abc"), size=3)
    assert ref.size == 3


def test_non_sha256_declared_checksum_is_rejected(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(StorageError):
        backend.put_stream(key="a.txt", stream=io.BytesIO(b"abc"), checksum="md5:abc")


def test_permissions_are_owner_only(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path / "root")
    backend.put_bytes(key="a/b/c.txt", content=b"x")
    mode = lambda p: stat.S_IMODE(p.stat().st_mode)  # noqa: E731
    assert mode(tmp_path / "root") == 0o700
    assert mode(tmp_path / "root" / "a" / "b") == 0o700
    assert mode(tmp_path / "root" / "a" / "b" / "c.txt") == 0o600


def test_local_oserrors_become_storage_errors(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="d/f.txt", content=b"x")
    directory = StoredObjectRef("", "local", "d", 0, "")
    with pytest.raises(StorageError):
        backend.get(directory)
    with pytest.raises(StorageError):
        backend.delete(directory)
    backend.delete(StoredObjectRef("", "local", "missing.txt", 0, ""))  # no error


def test_iter_locations_skips_temp_files(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="a/ok.txt", content=b"x")
    (tmp_path / "a" / ".granite-tmp-xyz").write_bytes(b"half")
    assert list(backend.iter_locations()) == ["a/ok.txt"]


def test_local_iter_locations_prefix_is_segment_based(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.put_bytes(key="docs/a.txt", content=b"x")
    backend.put_bytes(key="docs2/b.txt", content=b"x")
    assert list(backend.iter_locations("docs")) == ["docs/a.txt"]


# GS-008 ---------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Doc(StoredContentMixin, Base):
    __tablename__ = "docs_t"
    __stored_content_field_name__ = "_ref"
    __stored_content_storage_key__ = "docs"
    id: Mapped[str] = mapped_column(primary_key=True)
    _ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )


class _Upload:
    def __init__(self, data: bytes) -> None:
        self.file = io.BytesIO(data)
        self.filename = "a.txt"
        self.content_type = "text/plain"


def test_uploadfile_runs_io_off_the_event_loop(tmp_path: Path) -> None:
    Doc.configure_storage_manager(_manager(tmp_path))
    main = threading.get_ident()
    seen: list[int] = []
    manager = Doc.__storage_manager__
    assert manager is not None
    original = manager.put_stream

    def spy(**kwargs):
        seen.append(threading.get_ident())
        return original(**kwargs)

    manager.put_stream = spy  # type: ignore[method-assign]

    async def run() -> StoredObjectRef:
        obj = Doc(id=str(uuid.uuid4()))
        return await obj.set_content_from_uploadfile(_Upload(b"data"))  # type: ignore[arg-type]

    ref = asyncio.run(run())
    assert seen and seen[0] != main
    assert ref.size == 4
