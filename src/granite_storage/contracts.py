from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO, Protocol

from granite_storage.models import StoredObjectRef


class StorageBackend(Protocol):
    backend_name: str

    def put_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef: ...
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
    ) -> StoredObjectRef: ...
    def get(self, ref: StoredObjectRef) -> bytes: ...
    def open(self, ref: StoredObjectRef) -> BinaryIO: ...
    def delete(self, ref: StoredObjectRef) -> None: ...
    def exists(self, ref: StoredObjectRef) -> bool: ...
    def iter_locations(self, prefix: str | None = None) -> Iterator[str]: ...
