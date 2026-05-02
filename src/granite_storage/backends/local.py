from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import StorageError
from granite_storage.models import StoredObjectRef
from granite_storage.utils import DEFAULT_STREAM_CHUNK_SIZE, sha256_bytes, utcnow_iso


class LocalStorageBackend(StorageBackend):
    backend_name = "local"

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, location: str) -> Path:
        path = (self.root_dir / location).resolve()
        if self.root_dir not in path.parents and path != self.root_dir:
            raise StorageError("Invalid local storage path.")
        return path

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            len(content),
            sha256_bytes(content),
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
        import hashlib

        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        with path.open("wb") as f:
            while True:
                chunk = stream.read(DEFAULT_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                f.write(chunk)
        return StoredObjectRef(
            "",
            self.backend_name,
            key,
            size if size is not None else total,
            checksum or f"sha256:{digest.hexdigest()}",
            content_type,
            original_filename,
            utcnow_iso(),
            extra,
        )

    def get(self, ref: StoredObjectRef) -> bytes:
        path = self._resolve_path(ref.location)
        if not path.exists():
            raise StorageError(f"Local object not found: {ref.location}")
        return path.read_bytes()

    def open(self, ref: StoredObjectRef) -> BinaryIO:
        path = self._resolve_path(ref.location)
        if not path.exists():
            raise StorageError(f"Local object not found: {ref.location}")
        return path.open("rb")

    def delete(self, ref: StoredObjectRef) -> None:
        path = self._resolve_path(ref.location)
        if path.exists():
            path.unlink()

    def exists(self, ref: StoredObjectRef) -> bool:
        return self._resolve_path(ref.location).exists()

    def iter_locations(self, prefix: str | None = None) -> Iterator[str]:
        base = self.root_dir if not prefix else self._resolve_path(prefix)
        if not base.exists():
            return
        for path in base.rglob("*"):
            if path.is_file():
                yield path.relative_to(self.root_dir).as_posix()
