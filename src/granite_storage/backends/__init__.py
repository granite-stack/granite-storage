"""Storage backends.

``S3StorageBackend`` is imported lazily so that ``boto3`` stays optional
(install ``granite-storage[s3]`` to use it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from granite_storage.backends.local import LocalStorageBackend

if TYPE_CHECKING:
    from granite_storage.backends.s3 import S3StorageBackend

__all__ = ["LocalStorageBackend", "S3StorageBackend"]


def __getattr__(name: str) -> Any:
    if name == "S3StorageBackend":
        from granite_storage.backends.s3 import S3StorageBackend

        return S3StorageBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
