Implementing a New Backend
==========================

Granite Storage uses the ``StorageBackend`` protocol (``granite_storage.contracts``)
as its extension point. Any object that implements the protocol methods can be used
as a backend — no inheritance required.

The Protocol
------------

.. code-block:: python

   from typing import Any, BinaryIO, Iterator, Protocol
   from granite_storage.models import StoredObjectRef

   class StorageBackend(Protocol):
       backend_name: str  # unique identifier, e.g. "gcs" or "azure_blob"

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

Method Contracts
----------------

``put_bytes(*, key, content, ...)``
    Write ``content`` (``bytes``) at the logical path ``key`` inside the backend.
    Return a fully populated ``StoredObjectRef``.  The ``storage_key`` field of the
    returned ref is filled in by ``StorageManager`` after the call.

``put_stream(*, key, stream, ...)``
    Write from a file-like object.  The stream is wrapped by ``SizeLimitedStream``
    *before* it reaches the backend, so ``max_size`` enforcement is handled by the
    manager — the backend does **not** need to re-check it.  Compute checksum and
    byte count during the write.

``get(ref)``
    Return the full content as ``bytes``.  Raise ``StorageError`` if the object
    does not exist.

``open(ref)``
    Return a readable, binary file-like object.  The caller is responsible for
    closing it.  Raise ``StorageError`` if the object does not exist.

``delete(ref)``
    Remove the object from the backend.  Should be idempotent — do not raise if
    the object is already gone.

``exists(ref)``
    Return ``True`` if the object is present in the backend.

``iter_locations(prefix)``
    Yield every *location* (string key) stored in the backend, optionally filtered
    by ``prefix``.  Used by the garbage collector.

Example — Google Cloud Storage Backend
---------------------------------------

.. code-block:: python

   from __future__ import annotations

   import io
   from typing import Any, BinaryIO, Iterator

   from google.cloud import storage as gcs

   from granite_storage.exceptions import StorageError
   from granite_storage.models import StoredObjectRef
   from granite_storage.utils import sha256_bytes, utcnow_iso


   class GCSStorageBackend:
       """Google Cloud Storage backend for Granite Storage."""

       backend_name = "gcs"

       def __init__(self, *, bucket: str, prefix: str = "", client=None):
           self.bucket_name = bucket
           self.prefix = prefix.strip("/")
           self._client = client or gcs.Client()
           self._bucket = self._client.bucket(bucket)

       def _full_key(self, location: str) -> str:
           return f"{self.prefix}/{location}" if self.prefix else location

       def put_bytes(
           self,
           *,
           key: str,
           content: bytes,
           content_type: str | None = None,
           original_filename: str | None = None,
           extra: dict[str, Any] | None = None,
       ) -> StoredObjectRef:
           blob = self._bucket.blob(self._full_key(key))
           blob.upload_from_string(content, content_type=content_type or "application/octet-stream")
           return StoredObjectRef(
               storage_key="",
               backend=self.backend_name,
               location=key,
               size=len(content),
               checksum=sha256_bytes(content),
               content_type=content_type,
               original_filename=original_filename,
               created_at=utcnow_iso(),
               extra={"bucket": self.bucket_name, **(extra or {})},
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

           data = stream.read()          # stream is already size-limited by the manager
           digest = hashlib.sha256(data).hexdigest()
           blob = self._bucket.blob(self._full_key(key))
           blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
           return StoredObjectRef(
               storage_key="",
               backend=self.backend_name,
               location=key,
               size=size if size is not None else len(data),
               checksum=checksum or f"sha256:{digest}",
               content_type=content_type,
               original_filename=original_filename,
               created_at=utcnow_iso(),
               extra={"bucket": self.bucket_name, **(extra or {})},
           )

       def get(self, ref: StoredObjectRef) -> bytes:
           blob = self._bucket.blob(self._full_key(ref.location))
           if not blob.exists():
               raise StorageError(f"GCS object not found: {ref.location}")
           return blob.download_as_bytes()

       def open(self, ref: StoredObjectRef) -> BinaryIO:
           return io.BytesIO(self.get(ref))

       def delete(self, ref: StoredObjectRef) -> None:
           blob = self._bucket.blob(self._full_key(ref.location))
           if blob.exists():
               blob.delete()

       def exists(self, ref: StoredObjectRef) -> bool:
           return self._bucket.blob(self._full_key(ref.location)).exists()

       def iter_locations(self, prefix: str | None = None) -> Iterator[str]:
           blobs = self._bucket.list_blobs(prefix=self._full_key(prefix or ""))
           strip = f"{self.prefix}/" if self.prefix else ""
           for blob in blobs:
               yield blob.name[len(strip):]

Registering the New Backend
----------------------------

Pass your backend instance to ``StorageManager`` under a unique key:

.. code-block:: python

   from granite_storage import StorageManager, StoragePolicy

   manager = StorageManager(
       backends={"gcs": GCSStorageBackend(bucket="my-bucket")},
       policies={
           "uploads": StoragePolicy("uploads", backend_key="gcs", max_size=50*1024*1024),
       },
   )

Testing Your Backend
--------------------

The built-in test suite uses ``moto`` to mock S3 and a temporary directory for local
storage.  For a new backend, mock the external client in your tests:

.. code-block:: python

   from unittest.mock import MagicMock, patch
   import pytest
   from my_project.backends.gcs import GCSStorageBackend

   @pytest.fixture
   def mock_bucket():
       bucket = MagicMock()
       blob = MagicMock()
       bucket.blob.return_value = blob
       blob.exists.return_value = True
       blob.download_as_bytes.return_value = b"hello"
       return bucket

   def test_get_returns_bytes(mock_bucket):
       backend = GCSStorageBackend.__new__(GCSStorageBackend)
       backend.bucket_name = "test"
       backend.prefix = ""
       backend._bucket = mock_bucket

       from granite_storage.models import StoredObjectRef
       ref = StoredObjectRef(
           storage_key="uploads", backend="gcs", location="user/1/avatar/photo.jpg",
           size=5, checksum="sha256:abc",
       )
       assert backend.get(ref) == b"hello"

Checklist
---------

Before publishing a new backend, verify:

* ``put_bytes`` and ``put_stream`` return a ``StoredObjectRef`` with ``storage_key=""``
  (the manager fills it in).
* ``delete`` is idempotent — does not raise if the object is absent.
* ``iter_locations`` yields *bare* locations (without the backend prefix).
* ``open`` returns a file-like object that the caller can close normally.
* The ``backend_name`` class attribute is unique.
