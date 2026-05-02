Granite Storage Documentation
==============================

**Granite Storage** is a lightweight, backend-agnostic storage abstraction for Python applications.
It provides a unified API for storing and retrieving binary objects — locally or on S3 —
with first-class SQLAlchemy integration, streaming uploads, size-limit enforcement via policies,
and an optional garbage-collection engine for orphaned files.

Key Features
============

* **Backend-agnostic**: Swap between local filesystem and S3 without changing application code.
* **Policy-driven**: Define ``max_size``, ``key_prefix`` and backend routing per storage slot.
* **Streaming uploads**: Memory-safe streaming with size enforcement via ``SizeLimitedStream``.
* **SQLAlchemy integration**: ``StoredContentMixin`` and ``StoredObjectRefType`` turn any ORM model into a file-aware model.
* **Garbage collection**: ``StorageGarbageCollector`` scans for and removes orphaned objects.
* **Alembic helpers**: Portable column type helpers for migrations across PostgreSQL and SQLite.
* **Extensible**: Implement the ``StorageBackend`` protocol to add any new storage provider.

Quick Start
===========

Installation::

   pip install granite-storage

   # S3 support requires boto3 (already declared as a dependency):
   pip install granite-storage  # boto3 is included

Minimal local-storage example:

.. code-block:: python

   from granite_storage import StorageManager, StoragePolicy
   from granite_storage.backends.local import LocalStorageBackend

   backend = LocalStorageBackend(root_dir="/tmp/uploads")

   manager = StorageManager(
       backends={"local": backend},
       policies={
           "avatars": StoragePolicy(
               storage_key="avatars",
               backend_key="local",
               max_size=2 * 1024 * 1024,   # 2 MB
               key_prefix="avatars",
           ),
       },
   )

   # Store bytes
   with open("photo.jpg", "rb") as f:
       ref = manager.put_stream(
           storage_key="avatars",
           model_name="user",
           entity_id="42",
           field_name="avatar",
           stream=f,
           content_type="image/jpeg",
           original_filename="photo.jpg",
       )

   # Retrieve
   data = manager.get(ref)

Contents
========

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user-guide
   sqlalchemy-integration
   garbage-collection

.. toctree::
   :maxdepth: 2
   :caption: Developer Guide

   implementing-backend

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
