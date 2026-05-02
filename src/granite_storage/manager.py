from __future__ import annotations

import io
from collections.abc import Iterable
from typing import Any, BinaryIO

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import ContentTooLargeError, StorageError
from granite_storage.models import StoredObjectRef
from granite_storage.policies import StoragePolicy
from granite_storage.utils import build_storage_object_key


class SizeLimitedStream(io.BufferedIOBase, BinaryIO):
    def __init__(
        self, stream: BinaryIO, max_size: int | None, chunk_size: int = 1024 * 1024
    ):
        self.stream = stream
        self.max_size = max_size
        self.chunk_size = chunk_size
        self.total_read = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = self.stream.read(size if size and size > 0 else self.chunk_size)
        if chunk:
            self.total_read += len(chunk)
            if self.max_size is not None and self.total_read > self.max_size:
                raise ContentTooLargeError(
                    f"Content size exceeds max_size={self.max_size} bytes"
                )
        return chunk

    def __enter__(self) -> SizeLimitedStream:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        self.stream.close()

    def fileno(self) -> int:
        return self.stream.fileno()

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return self.stream.isatty()

    def readable(self) -> bool:
        return True

    def readline(self, limit: int | None = -1) -> bytes:
        return self.stream.readline(limit if limit is not None else -1)

    def readlines(self, hint: int = -1) -> list[bytes]:
        return self.stream.readlines(hint)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def seekable(self) -> bool:
        return self.stream.seekable()

    def tell(self) -> int:
        return self.stream.tell()

    def truncate(self, size: int | None = None) -> int:
        return self.stream.truncate(size)

    def writable(self) -> bool:
        return False

    def write(self, __s: Any) -> int:
        raise io.UnsupportedOperation("write")

    def writelines(self, lines: Iterable[Any]) -> None:
        raise io.UnsupportedOperation("writelines")

    def __iter__(self) -> SizeLimitedStream:
        return self

    def __next__(self) -> bytes:
        chunk = self.read(self.chunk_size)
        if not chunk:
            raise StopIteration
        return chunk


class StorageManager:
    def __init__(
        self, backends: dict[str, StorageBackend], policies: dict[str, StoragePolicy]
    ):
        self.backends = backends
        self.policies = policies

    def get_policy(self, storage_key: str) -> StoragePolicy:
        try:
            return self.policies[storage_key]
        except KeyError as exc:
            raise StorageError(f"Unknown storage policy: {storage_key}") from exc

    def get_backend_for_policy(self, policy: StoragePolicy) -> StorageBackend:
        try:
            return self.backends[policy.backend_key]
        except KeyError as exc:
            raise StorageError(f"Unknown backend: {policy.backend_key}") from exc

    def _build_location(
        self,
        policy: StoragePolicy,
        *,
        model_name: str,
        entity_id: Any,
        field_name: str,
        original_filename: str | None,
    ) -> str:
        model_path = (
            model_name if not policy.key_prefix else f"{policy.key_prefix}/{model_name}"
        )
        return build_storage_object_key(
            model_name=model_path,
            entity_id=entity_id,
            field_name=field_name,
            original_filename=original_filename,
        )

    def put_bytes(
        self,
        *,
        storage_key: str,
        model_name: str,
        entity_id: Any,
        field_name: str,
        content: bytes,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        policy = self.get_policy(storage_key)
        if (
            policy.max_size is not None
            and len(content) > policy.max_size
        ):
            raise ContentTooLargeError(
                f"Content size {len(content)} exceeds max_size="
                f"{policy.max_size} for {storage_key}"
            )
        location = self._build_location(
            policy,
            model_name=model_name,
            entity_id=entity_id,
            field_name=field_name,
            original_filename=original_filename,
        )
        backend = self.get_backend_for_policy(policy)
        ref = backend.put_bytes(
            key=location,
            content=content,
            content_type=content_type,
            original_filename=original_filename,
            extra=extra,
        )
        ref.storage_key = storage_key
        return ref

    def put_stream(
        self,
        *,
        storage_key: str,
        model_name: str,
        entity_id: Any,
        field_name: str,
        stream: BinaryIO,
        content_type: str | None = None,
        original_filename: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StoredObjectRef:
        policy = self.get_policy(storage_key)
        location = self._build_location(
            policy,
            model_name=model_name,
            entity_id=entity_id,
            field_name=field_name,
            original_filename=original_filename,
        )
        backend = self.get_backend_for_policy(policy)
        limited_stream = SizeLimitedStream(stream, max_size=policy.max_size)
        ref = backend.put_stream(
            key=location,
            stream=limited_stream,
            content_type=content_type,
            original_filename=original_filename,
            extra=extra,
        )
        ref.storage_key = storage_key
        return ref

    def get(self, ref: StoredObjectRef) -> bytes:
        return self.get_backend_for_policy(self.get_policy(ref.storage_key)).get(ref)

    def open(self, ref: StoredObjectRef) -> BinaryIO:
        return self.get_backend_for_policy(self.get_policy(ref.storage_key)).open(ref)

    def delete(self, ref: StoredObjectRef) -> None:
        self.get_backend_for_policy(self.get_policy(ref.storage_key)).delete(ref)

    def exists(self, ref: StoredObjectRef) -> bool:
        return self.get_backend_for_policy(self.get_policy(ref.storage_key)).exists(ref)
