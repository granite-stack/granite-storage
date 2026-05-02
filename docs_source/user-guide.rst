User Guide
==========

This guide covers the complete workflow: configuring the manager, defining policies,
integrating with SQLAlchemy ORM models, running garbage collection, and using Alembic
helpers for migrations.

Architecture Overview
---------------------

Granite Storage has three layers:

``StorageManager``
    The central object your application interacts with. It dispatches operations to
    the right backend according to the named *policy*.

``StoragePolicy``
    A frozen dataclass that binds a *storage key* (logical slot name) to a *backend key*,
    with optional ``max_size`` and ``key_prefix``.

``StorageBackend``
    A protocol (interface) implemented by ``LocalStorageBackend``, ``S3StorageBackend``,
    or any custom backend. See :doc:`implementing-backend`.

``StoredObjectRef``
    A dataclass returned by every write operation. It is the *receipt* of the stored
    object: it contains ``location``, ``size``, ``checksum``, ``content_type``, and
    ``original_filename``. You persist this in your database.

Configuring the Manager
-----------------------

.. code-block:: python

   from granite_storage import StorageManager, StoragePolicy
   from granite_storage.backends.local import LocalStorageBackend
   from granite_storage.backends.s3 import S3StorageBackend

   manager = StorageManager(
       backends={
           "local": LocalStorageBackend(root_dir="/var/uploads"),
           "s3":    S3StorageBackend(bucket="my-bucket"),
       },
       policies={
           "avatars": StoragePolicy(
               storage_key="avatars",
               backend_key="local",
               max_size=2 * 1024 * 1024,
               key_prefix="avatars",
           ),
           "attachments": StoragePolicy(
               storage_key="attachments",
               backend_key="s3",
               max_size=20 * 1024 * 1024,
               key_prefix="attach",
           ),
       },
   )

Storage Key Naming
------------------

The ``storage_key`` is the *logical name* your application uses to refer to a storage
slot (e.g. ``"avatars"``, ``"course_banners"``, ``"quiz_attachments"``). It does **not**
have to match any file-system path.

The ``key_prefix`` is an optional path segment prepended to the generated object key
inside the backend. For example:

* ``key_prefix="avatars"`` + ``model_name="user"`` + ``entity_id="42"`` + ``field_name="avatar"``
  → location ``avatars/user/42/avatar/<filename>``

Without a prefix the location starts directly with ``model_name``.

Storing Content
---------------

**From bytes** (small files, already in memory):

.. code-block:: python

   ref = manager.put_bytes(
       storage_key="avatars",
       model_name="user",
       entity_id=str(user.id),
       field_name="avatar",
       content=image_bytes,
       content_type="image/png",
       original_filename="avatar.png",
   )

**From a stream** (large files, avoids loading into RAM):

.. code-block:: python

   with open("video.mp4", "rb") as f:
       ref = manager.put_stream(
           storage_key="attachments",
           model_name="lesson",
           entity_id=str(lesson.id),
           field_name="video",
           stream=f,
           content_type="video/mp4",
           original_filename="video.mp4",
       )

The stream path enforces ``max_size`` transparently via ``SizeLimitedStream``. A
``ContentTooLargeError`` is raised as soon as the threshold is exceeded, so your process
never buffers an oversized payload in memory.

Retrieving Content
------------------

.. code-block:: python

   # Full bytes (only for small objects)
   data: bytes = manager.get(ref)

   # File-like object (preferred for large files)
   with manager.open(ref) as fh:
       send_to_client(fh)

Checking Existence & Deleting
------------------------------

.. code-block:: python

   if manager.exists(ref):
       manager.delete(ref)

The ``StoredObjectRef``
-----------------------

After each write you receive a ``StoredObjectRef``:

.. code-block:: python

   @dataclass
   class StoredObjectRef:
       storage_key: str          # logical policy name, e.g. "avatars"
       backend: str              # backend name, e.g. "local" or "s3"
       location: str             # path inside the backend
       size: int                 # bytes written
       checksum: str             # "sha256:<hex>"
       content_type: str | None
       original_filename: str | None
       created_at: str | None    # ISO 8601 UTC
       extra: dict | None        # backend-specific metadata

Persist it as JSON in your database (see :doc:`sqlalchemy-integration`).
