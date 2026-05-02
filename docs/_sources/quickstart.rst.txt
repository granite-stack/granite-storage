Quick Start
===========

This page shows the two most common setups — local filesystem and AWS S3 — so you can
be productive in minutes.

Local Storage
-------------

Good for development and single-server deployments.

.. code-block:: python

   from granite_storage import StorageManager, StoragePolicy
   from granite_storage.backends.local import LocalStorageBackend

   # 1. Create a backend pointing at a directory on disk.
   backend = LocalStorageBackend(root_dir="/var/app/uploads")

   # 2. Define policies (one per "storage slot").
   policies = {
       "avatars": StoragePolicy(
           storage_key="avatars",
           backend_key="local",
           max_size=2 * 1024 * 1024,  # 2 MB
           key_prefix="avatars",
       ),
       "documents": StoragePolicy(
           storage_key="documents",
           backend_key="local",
           max_size=10 * 1024 * 1024,  # 10 MB
           key_prefix="docs",
       ),
   }

   # 3. Build the manager.
   manager = StorageManager(backends={"local": backend}, policies=policies)

   # 4. Store a file from bytes.
   ref = manager.put_bytes(
       storage_key="avatars",
       model_name="user",
       entity_id="user-123",
       field_name="avatar",
       content=open("photo.jpg", "rb").read(),
       content_type="image/jpeg",
       original_filename="photo.jpg",
   )
   print(ref.location)   # avatars/user/user-123/avatar/photo.jpg

   # 5. Stream a large file (memory-safe).
   with open("report.pdf", "rb") as f:
       ref = manager.put_stream(
           storage_key="documents",
           model_name="report",
           entity_id="rpt-456",
           field_name="file",
           stream=f,
           content_type="application/pdf",
           original_filename="report.pdf",
       )

   # 6. Retrieve content.
   data: bytes = manager.get(ref)

   # 7. Open as a file-like object (streaming read).
   with manager.open(ref) as fh:
       first_bytes = fh.read(512)

   # 8. Delete.
   manager.delete(ref)

S3 Storage
----------

Replace the backend with ``S3StorageBackend``. Everything else stays the same.

.. code-block:: python

   import boto3
   from granite_storage import StorageManager, StoragePolicy
   from granite_storage.backends.s3 import S3StorageBackend

   s3_client = boto3.client("s3", region_name="us-east-1")

   backend = S3StorageBackend(
       bucket="my-app-uploads",
       prefix="production",          # optional key prefix inside the bucket
       client=s3_client,
       extra_put_kwargs={"ACL": "private"},  # any extra boto3 put_object kwargs
   )

   manager = StorageManager(
       backends={"s3": backend},
       policies={
           "avatars": StoragePolicy(
               storage_key="avatars",
               backend_key="s3",
               max_size=2 * 1024 * 1024,
               key_prefix="avatars",
           ),
       },
   )

   # API is identical to local storage.
   with open("photo.jpg", "rb") as f:
       ref = manager.put_stream(
           storage_key="avatars",
           model_name="user",
           entity_id="user-123",
           field_name="avatar",
           stream=f,
           content_type="image/jpeg",
           original_filename="photo.jpg",
       )

Mixed Backends
--------------

You can register multiple backends in a single ``StorageManager`` and route each
policy to a different one:

.. code-block:: python

   from granite_storage.backends.local import LocalStorageBackend
   from granite_storage.backends.s3 import S3StorageBackend

   manager = StorageManager(
       backends={
           "local": LocalStorageBackend(root_dir="/tmp/dev"),
           "s3":    S3StorageBackend(bucket="prod-bucket"),
       },
       policies={
           "thumbnails": StoragePolicy("thumbnails", backend_key="local", max_size=512*1024),
           "originals":  StoragePolicy("originals",  backend_key="s3",    max_size=50*1024*1024),
       },
   )

Error Handling
--------------

.. code-block:: python

   from granite_storage import ContentTooLargeError, StorageError

   try:
       ref = manager.put_bytes(storage_key="avatars", ..., content=huge_bytes)
   except ContentTooLargeError as e:
       # HTTP 413 — content exceeds the policy max_size
       print(f"File too large: {e}")
   except StorageError as e:
       # Any other storage problem (missing policy, backend error, etc.)
       print(f"Storage error: {e}")
