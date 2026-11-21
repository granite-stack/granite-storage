from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from typing import Any, BinaryIO

from granite_storage.contracts import StorageBackend
from granite_storage.exceptions import (
    ContentTooLargeError,
    ContentTypeNotAllowedError,
    StorageError,
)
from granite_storage.models import StoredObjectRef
from granite_storage.policies import StoragePolicy
from granite_storage.utils import (
    build_storage_object_key,
    content_type_allowed,
    normalize_content_type,
    sanitize_filename,
    verify_declared_checksum,
)


class SizeLimitedStream(io.BufferedIOBase, BinaryIO):
    """Read-only wrapper that enforces a cumulative size limit.

    Every read path (``read``, ``read1``, ``readinto``, ``readline``,
    ``readlines`` and iteration) counts the bytes it returns and raises
    :class:`ContentTooLargeError` once ``max_size`` is exceeded.

    The wrapped stream belongs to the caller: ``close()`` (and garbage
    collection) only marks this wrapper as closed and never closes it.
    The wrapper is not seekable, because rewinding would break the count.
    """

    def __init__(
        self, stream: BinaryIO, max_size: int | None, chunk_size: int = 1024 * 1024
    ):
        self.stream = stream
        self.max_size = max_size
        self.chunk_size = chunk_size
        self.total_read = 0

    def _count(self, data: bytes) -> bytes:
        if data:
            self.total_read += len(data)
            if self.max_size is not None and self.total_read > self.max_size:
                raise ContentTooLargeError(
                    f"Content size exceeds max_size={self.max_size} bytes"
                )
        return data

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            parts: list[bytes] = []
            while True:
                chunk = self._count(self.stream.read(self.chunk_size))
                if not chunk:
                    return b"".join(parts)
                parts.append(chunk)
        if size == 0:
            return b""
        return self._count(self.stream.read(size))

    def read1(self, size: int = -1) -> bytes:
        return self._count(self.stream.read(size if size > 0 else self.chunk_size))

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        data = self.read(len(view))
        view[: len(data)] = data
        return len(data)

    def readline(self, limit: int | None = -1) -> bytes:
        return self._count(self.stream.readline(limit if limit is not None else -1))

    def readlines(self, hint: int = -1) -> list[bytes]:
        lines: list[bytes] = []
        total = 0
        while True:
            line = self.readline()
            if not line:
                return lines
            lines.append(line)
            total += len(line)
            if 0 < hint <= total:
                return lines

    def __enter__(self) -> SizeLimitedStream:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def fileno(self) -> int:
        return self.stream.fileno()

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return self.stream.isatty()

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        raise io.UnsupportedOperation("seek")

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.total_read

    def truncate(self, size: int | None = None) -> int:
        raise io.UnsupportedOperation("truncate")

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

    def _check_write_metadata(
        self,
        policy: StoragePolicy,
        content_type: str | None,
        original_filename: str | None,
    ) -> tuple[str | None, str | None]:
        """Validate client-supplied metadata; return (content_type, filename)."""
        content_type = normalize_content_type(content_type)
        if policy.allowed_content_types is not None and not content_type_allowed(
            content_type, policy.allowed_content_types
        ):
            raise ContentTypeNotAllowedError(
                f"Content type {content_type!r} is not allowed for "
                f"{policy.storage_key}."
            )
        return content_type, sanitize_filename(original_filename)

    def _resolve_ref(self, ref: StoredObjectRef) -> tuple[StorageBackend, str]:
        """Pick the backend for *ref* after checking it against the policy.

        The reference must have been written by this policy's backend
        (``ref.backend`` equal to the backend's ``backend_name``; an empty
        value is tolerated for very old references) and its ``location`` must
        lie under ``key_prefix`` or one of ``legacy_key_prefixes``.
        """
        policy = self.get_policy(ref.storage_key)
        backend = self.get_backend_for_policy(policy)
        backend_name = getattr(backend, "backend_name", None)
        if ref.backend and backend_name and ref.backend != backend_name:
            raise StorageError(
                f"Reference was stored in backend '{ref.backend}' but policy "
                f"'{policy.storage_key}' uses '{backend_name}'."
            )
        prefixes = policy.read_prefixes
        if prefixes and not any(ref.location.startswith(f"{p}/") for p in prefixes):
            raise StorageError(
                f"Reference location is outside the prefixes of policy "
                f"'{policy.storage_key}'."
            )
        return backend, policy.storage_key

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
        content_type, original_filename = self._check_write_metadata(
            policy, content_type, original_filename
        )
        if policy.max_size is not None and len(content) > policy.max_size:
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
        content_type, original_filename = self._check_write_metadata(
            policy, content_type, original_filename
        )
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

    def get(self, ref: StoredObjectRef, *, verify_checksum: bool = False) -> bytes:
        """Read an object; with ``verify_checksum`` compare it to ``ref.checksum``."""
        backend, _ = self._resolve_ref(ref)
        data = backend.get(ref)
        if verify_checksum and ref.checksum:
            verify_declared_checksum(ref.checksum, hashlib.sha256(data).hexdigest())
        return data

    def open(self, ref: StoredObjectRef) -> BinaryIO:
        return self._resolve_ref(ref)[0].open(ref)

    def delete(self, ref: StoredObjectRef) -> None:
        self._resolve_ref(ref)[0].delete(ref)

    def exists(self, ref: StoredObjectRef) -> bool:
        return self._resolve_ref(ref)[0].exists(ref)
