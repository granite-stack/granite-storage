from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef
from granite_storage.utils import (
    DEFAULT_STREAM_CHUNK_SIZE,
    utcnow_iso,
    validate_storage_key,
    verify_declared_checksum,
)

TEMP_PREFIX = ".granite-tmp-"


class LocalStorageBackend(StorageBackend):
    """Store objects as files under ``root_dir``.

    Writes are atomic: data goes to a temporary file in the destination
    directory and is moved into place with ``os.replace`` only when complete,
    so a failed or oversized upload never leaves a partial file and never
    destroys an existing one. Directories are created with ``dir_mode`` and
    files with ``file_mode`` (owner-only by default).
    """

    backend_name = "local"

    def __init__(
        self,
        root_dir: str | Path,
        *,
        dir_mode: int = 0o700,
        file_mode: int = 0o600,
    ):
        self.dir_mode = dir_mode
        self.file_mode = file_mode
        self.root_dir = Path(root_dir).resolve()
        self._makedirs(self.root_dir)

    def _makedirs(self, directory: Path) -> None:
        missing: list[Path] = []
        current = directory
        while not current.exists():
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            try:
                path.mkdir(mode=self.dir_mode, exist_ok=True)
                path.chmod(self.dir_mode)
            except OSError as exc:
                raise StorageError(f"Cannot create directory {path}: {exc}") from exc

    def _resolve_path(self, location: str, *, is_prefix: bool = False) -> Path:
        try:
            validate_storage_key(location, is_prefix=is_prefix)
        except StorageError as exc:
            raise StorageError(f"Invalid local storage path. {exc}") from exc
        path = (self.root_dir / location).resolve()
        if path == self.root_dir or not path.is_relative_to(self.root_dir):
            raise StorageError("Invalid local storage path.")
        return path

    def _write_atomic(
        self,
        path: Path,
        chunks: Iterator[bytes],
        *,
        size: int | None = None,
        checksum: str | None = None,
    ) -> tuple[int, str]:
        """Write *chunks* to *path* atomically; return (size, sha256 hex).

        Declared ``size``/``checksum`` are verified before publishing.
        """
        self._makedirs(path.parent)
        digest = hashlib.sha256()
        total = 0
        tmp_name = ""
        try:
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX)
            with os.fdopen(fd, "wb") as f:
                for chunk in chunks:
                    total += len(chunk)
                    digest.update(chunk)
                    f.write(chunk)
            if size is not None and size != total:
                raise StorageError(
                    f"Declared size {size} does not match written size {total}."
                )
            verify_declared_checksum(checksum, digest.hexdigest())
            os.chmod(tmp_name, self.file_mode)
            os.replace(tmp_name, path)
        except BaseException as exc:
            if tmp_name:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
            if isinstance(exc, OSError):
                raise StorageError(f"Local write failed: {exc}") from exc
            raise
        return total, digest.hexdigest()

    def put_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        path = self._resolve_path(key)
        total, hexdigest = self._write_atomic(path, iter([content]))
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            total,
            f"sha256:{hexdigest}",
            content_type,
            original_filename,
            utcnow_iso(),
            extra,
        )

    def put_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        size: int | None = None,
        checksum: str | None = None,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        """Store *stream*; ``size``/``checksum``, if given, are verified.

        A mismatch with what was actually written raises ``StorageError`` and
        leaves no object behind.
        """
        path = self._resolve_path(key)

        def chunks() -> Iterator[bytes]:
            while chunk := stream.read(DEFAULT_STREAM_CHUNK_SIZE):
                yield chunk

        total, hexdigest = self._write_atomic(
            path, chunks(), size=size, checksum=checksum
        )
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            total,
            f"sha256:{hexdigest}",
            content_type,
            original_filename,
            utcnow_iso(),
            extra,
        )

    def get(self, ref: StoredObjectRef) -> bytes:
        path = self._resolve_path(ref.location)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Local object not found: {ref.location}") from exc
        except OSError as exc:
            raise StorageError(f"Local read failed for {ref.location}: {exc}") from exc

    def open(self, ref: StoredObjectRef) -> BinaryIO:
        path = self._resolve_path(ref.location)
        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise StorageError(f"Local object not found: {ref.location}") from exc
        except OSError as exc:
            raise StorageError(f"Local open failed for {ref.location}: {exc}") from exc

    def delete(self, ref: StoredObjectRef) -> None:
        path = self._resolve_path(ref.location)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Local delete failed for {ref.location}: {exc}"
            ) from exc

    def exists(self, ref: StoredObjectRef) -> bool:
        return self._resolve_path(ref.location).is_file()

    def last_modified(self, location: str) -> datetime | None:
        """Modification time of *location*, or ``None`` if it does not exist."""
        try:
            mtime = self._resolve_path(location).stat().st_mtime
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(f"Local stat failed for {location}: {exc}") from exc
        return datetime.fromtimestamp(mtime, UTC)

    def iter_locations(self, prefix: str | None = None) -> Iterator[str]:
        """Yield stored locations under *prefix* (whole path segments only)."""
        base = (
            self.root_dir if not prefix else self._resolve_path(prefix, is_prefix=True)
        )
        if not base.is_dir():
            return
        for path in base.rglob("*"):
            if path.is_file() and not path.name.startswith(TEMP_PREFIX):
                yield path.relative_to(self.root_dir).as_posix()
