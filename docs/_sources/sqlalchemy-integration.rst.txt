SQLAlchemy Integration
======================

Granite Storage ships with first-class SQLAlchemy support: a column type that
transparently serialises ``StoredObjectRef`` to/from JSON, a mixin that adds
file-handling methods directly to any ORM model, and an Alembic helper for
portable column definitions.

StoredObjectRefType — Column Type
----------------------------------

Use ``StoredObjectRefType`` as the column type for any column that stores a
file reference. It wraps SQLAlchemy's ``JSON`` (PostgreSQL: ``JSONB``) and
automatically converts between the column value and a ``StoredObjectRef``
instance.

.. code-block:: python

   from sqlalchemy import String
   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
   from granite_storage import StoredObjectRef, StoredObjectRefType

   class Base(DeclarativeBase):
       pass

   class UserProfile(Base):
       __tablename__ = "user_profile"

       id: Mapped[str] = mapped_column(String, primary_key=True)
       name: Mapped[str] = mapped_column(String)
       avatar: Mapped[StoredObjectRef | None] = mapped_column(
           StoredObjectRefType, nullable=True
       )

When you read the row back from the database ``avatar`` is already a
``StoredObjectRef`` (or ``None``). No manual ``from_dict`` / ``to_dict`` needed.

StoredContentMixin — File-Aware Models
---------------------------------------

``StoredContentMixin`` adds ``set_content()``, ``set_content_stream()``,
``get_content()``, and ``delete_content()`` helpers directly to your model class.
You only need to declare two class variables:

* ``__stored_content_field_name__`` — the attribute that holds the ``StoredObjectRef``.
* ``__stored_content_storage_key__`` — the policy name to use by default.

Then configure the manager at startup and inject it into the class.

.. code-block:: python

   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
   from granite_storage import (
       StorageManager, StoragePolicy, StoredContentMixin,
       StoredObjectRef, StoredObjectRefType,
   )
   from granite_storage.backends.local import LocalStorageBackend

   class Base(DeclarativeBase):
       pass

   class Document(Base, StoredContentMixin):
       __tablename__ = "document"
       __stored_content_field_name__ = "_file_ref"
       __stored_content_storage_key__ = "documents"

       id: Mapped[int] = mapped_column(primary_key=True)
       title: Mapped[str] = mapped_column()
       _file_ref: Mapped[StoredObjectRef | None] = mapped_column(
           StoredObjectRefType, nullable=True
       )

   # Inject the manager once at startup
   manager = StorageManager(
       backends={"local": LocalStorageBackend("/var/uploads")},
       policies={
           "documents": StoragePolicy("documents", "local", max_size=10*1024*1024),
       },
   )
   Document.__storage_manager__ = manager

   # Now any instance can store content
   doc = Document(id=1, title="Report")
   session.add(doc)
   session.flush()  # ensure id is set

   doc.set_content(pdf_bytes, filename="report.pdf", content_type="application/pdf")
   session.commit()

   # Replace existing content
   result = doc.replace_content(new_pdf_bytes, filename="report-v2.pdf")
   # result.previous_ref  →  the old StoredObjectRef (for cleanup)
   # result.new_ref        →  the new StoredObjectRef

   # Read back
   data = doc.get_content()   # bytes

   # Delete stored file (sets _file_ref to None)
   doc.delete_content()
   session.commit()

Alembic — Portable Column Type
--------------------------------

When writing Alembic migrations use ``portable_storage_ref_type()`` so that the
column is ``JSON`` on SQLite and ``JSONB`` on PostgreSQL without duplication:

.. code-block:: python

   import sqlalchemy as sa
   from alembic import op
   from granite_storage import portable_storage_ref_type

   def upgrade():
       op.add_column(
           "document",
           sa.Column("_file_ref", portable_storage_ref_type(), nullable=True),
       )

   def downgrade():
       op.drop_column("document", "_file_ref")

Migrating an Existing Text Column
----------------------------------

If you have a column that previously stored inline text and want to migrate it
to a ``StoredObjectRef`` JSON column on PostgreSQL:

.. code-block:: python

   from alembic import op
   import sqlalchemy as sa
   from sqlalchemy.dialects import postgresql

   def upgrade():
       op.alter_column(
           "section_item",
           "content_markdown",
           existing_type=sa.Text(),
           type_=sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
           postgresql_using=(
               "CASE WHEN content_markdown IS NULL THEN NULL "
               "ELSE jsonb_build_object('legacy_inline_text', content_markdown) END"
           ),
           existing_nullable=True,
       )
