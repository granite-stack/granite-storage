Garbage Collection
==================

Over time, stored objects can become *orphaned* — they exist in the backend but
no database row holds a reference to them. This happens when:

* A row is deleted without calling ``manager.delete(ref)`` first.
* An upload succeeded but the database transaction was rolled back.
* Content was replaced and the old ``StoredObjectRef`` was overwritten without
  deleting the old object from the backend.

``StorageGarbageCollector`` scans all objects in a backend and deletes those
that are not referenced in the database.

How It Works
------------

1. Collect all ``StoredObjectRef`` values currently stored in the database
   (the *referenced* set).
2. Ask the backend to list all objects with ``iter_locations()``.
3. Any object whose ``location`` is **not** in the referenced set is *orphaned*.
4. In ``dry_run=True`` mode (default) only count them.  In ``dry_run=False`` mode
   delete them.

Basic Usage
-----------

.. code-block:: python

   from sqlalchemy.orm import Session
   from granite_storage.gc import StorageGarbageCollector
   from granite_storage.integrations.sqlalchemy import iter_model_storage_refs

   def collect_referenced_refs(session: Session):
       """Yield every StoredObjectRef currently stored in the DB."""
       yield from iter_model_storage_refs(session, Document, "_file_ref")
       yield from iter_model_storage_refs(session, UserProfile, "avatar")

   with Session(engine) as session:
       gc = StorageGarbageCollector(
           manager=manager,
           iter_references=lambda: collect_referenced_refs(session),
       )

       # Dry run — just count orphans
       report = gc.collect(storage_key="documents", dry_run=True)
       print(f"Orphaned: {report.orphaned} / {report.scanned} objects scanned")

       # Real run — delete orphans
       report = gc.collect(storage_key="documents", dry_run=False)
       print(f"Deleted {report.deleted} orphaned objects")

GarbageCollectionReport
------------------------

.. code-block:: python

   @dataclass
   class GarbageCollectionReport:
       scanned: int     # total objects found in the backend
       referenced: int  # objects with a live DB reference
       orphaned: int    # objects with no DB reference
       deleted: int     # objects actually deleted (0 if dry_run=True)

Scheduling
----------

Run garbage collection as a periodic background task. With **ARQ**:

.. code-block:: python

   async def run_gc(ctx):
       async with AsyncSession(engine) as session:
           gc = StorageGarbageCollector(
               manager=manager,
               iter_references=lambda: collect_referenced_refs(session),
           )
           report = gc.collect(storage_key="documents", dry_run=False)
           print(report)

Or as a simple cron job that calls a management CLI command.

.. warning::

   Always run garbage collection **after** confirming that all in-flight
   transactions have committed. Running it during a high-write period may
   delete objects that are about to be referenced.

``iter_model_storage_refs`` Helper
------------------------------------

``granite_storage.integrations.sqlalchemy.iter_model_storage_refs`` is a
convenience function that queries a SQLAlchemy column for non-null values:

.. code-block:: python

   from granite_storage.integrations.sqlalchemy import iter_model_storage_refs

   for ref in iter_model_storage_refs(session, MyModel, "file_ref_column"):
       print(ref.location)
