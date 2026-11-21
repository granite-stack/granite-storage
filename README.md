# granite-storage

[![PyPI version](https://img.shields.io/pypi/v/granite-storage.svg)](https://pypi.org/project/granite-storage/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Python](https://img.shields.io/pypi/pyversions/granite-storage.svg)](https://pypi.org/project/granite-storage/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**granite-storage** is a lightweight, backend-agnostic storage abstraction for SQLAlchemy 2 models.
It decouples the physical storage of files from your ORM models with a clean API designed for
FastAPI services and any async-friendly Python application.

## Features

- **Backend-agnostic** — swap between local filesystem and Amazon S3 without changing application code.
- **Policy-driven routing** — configure `max_size`, `key_prefix`, and backend per storage slot.
- **Streaming uploads** — memory-safe streaming with automatic size enforcement via `SizeLimitedStream`.
- **SQLAlchemy integration** — `StoredContentMixin` and `StoredObjectRefType` turn any ORM model into a file-aware model with zero boilerplate.
- **FastAPI support** — `set_content_from_uploadfile()` accepts FastAPI `UploadFile` directly.
- **Garbage collection** — `StorageGarbageCollector` scans for and removes orphaned objects.
- **Alembic helpers** — portable `JSON`/`JSONB` column type for cross-database migrations.
- **Type-safe** — full type hints throughout; compatible with mypy strict mode.

## Requirements

- Python 3.12+
- SQLAlchemy 2.0+
- boto3 1.34+ (only for the S3 backend, installed with the `s3` extra)

## Installation

```bash
pip install granite-storage          # local backend only
pip install "granite-storage[s3]"    # adds boto3 for the S3 backend
```

With UV:

```bash
uv add granite-storage              # or: uv add "granite-storage[s3]"
```

`S3StorageBackend` raises an `ImportError` explaining this if boto3 is missing.

For development:

```bash
git clone https://github.com/granite-stack/granite-storage.git
cd granite-storage
uv sync --all-extras
```

## Quick Start

### 1. Configure backends and policies

```python
from granite_storage import StorageManager, StoragePolicy
from granite_storage.backends.local import LocalStorageBackend

manager = StorageManager(
    backends={
        "local": LocalStorageBackend("./var/storage"),
    },
    policies={
        "avatars": StoragePolicy(
            storage_key="avatars",
            backend_key="local",
            max_size=2 * 1024 * 1024,   # 2 MB
            key_prefix="avatars",
        ),
        "documents": StoragePolicy(
            storage_key="documents",
            backend_key="local",
            max_size=10 * 1024 * 1024,  # 10 MB
            key_prefix="docs",
        ),
    },
)
```

### 2. Define a file-aware SQLAlchemy model

```python
import uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from granite_storage import (
    StoredContentMixin,
    StoredObjectRef,
    StoredObjectRefType,
)

class Base(DeclarativeBase):
    pass

class Document(StoredContentMixin, Base):
    __tablename__ = "document"
    __stored_content_field_name__ = "_file_ref"
    __stored_content_storage_key__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column()
    _file_ref: Mapped[StoredObjectRef | None] = mapped_column(
        StoredObjectRefType(), nullable=True
    )

# Inject the manager once at startup
Document.configure_storage_manager(manager)
```

### 3. Store and retrieve content

```python
with Session(engine) as session:
    doc = Document(title="Annual Report")
    session.add(doc)
    session.flush()  # ensure id is set before storing the file

    # From bytes
    doc.set_content(pdf_bytes, filename="report.pdf", content_type="application/pdf")
    session.commit()

    # From a stream (memory-safe for large files)
    with open("video.mp4", "rb") as f:
        doc.set_content_from_stream(f, filename="video.mp4", content_type="video/mp4")
    session.commit()

    # From a FastAPI UploadFile
    await doc.set_content_from_uploadfile(upload_file)
    session.commit()

    # Read back
    data: bytes = doc.get_content()
    with doc.open_content() as fh:
        first_chunk = fh.read(8192)

    # Replace: every write goes to a NEW object key, so the old object is
    # still intact until you delete it (after the commit succeeds).
    result = doc.replace_content(new_bytes, filename="report-v2.pdf")
    # result.previous_ref — the old StoredObjectRef (delete it after commit)
    # result.new_ref      — the new StoredObjectRef

    # Remove the reference (does NOT delete the physical file)
    old_ref = doc.clear_content_reference()
    session.commit()
```

### 4. Use the manager directly (without the mixin)

```python
ref = manager.put_stream(
    storage_key="avatars",
    model_name="user",
    entity_id=str(user.id),
    field_name="avatar",
    stream=image_stream,
    content_type="image/jpeg",
    original_filename="photo.jpg",
)
# ref is a StoredObjectRef — persist it in your database as JSON

data = manager.get(ref)
manager.delete(ref)
```

### 5. S3 backend

```python
import boto3
from granite_storage.backends.s3 import S3StorageBackend

manager = StorageManager(
    backends={
        "s3": S3StorageBackend(
            bucket="my-app-uploads",
            prefix="production",
            client=boto3.client("s3", region_name="us-east-1"),
        ),
    },
    policies={
        "avatars": StoragePolicy("avatars", backend_key="s3", max_size=2*1024*1024),
    },
)
```

## Recommended Workflow

1. Create the entity and call `session.add(obj)`.
2. Call `session.flush()` so the primary key is available before storing the file.
3. Call `set_content()`, `set_content_from_stream()`, or `set_content_from_uploadfile()`.
4. Call `session.commit()`.
5. If the transaction fails, the physical object may become orphaned — the garbage collector will clean it up later.

## Error Handling

```python
from granite_storage import ContentTooLargeError, StorageError

try:
    ref = manager.put_bytes(storage_key="avatars", ..., content=huge_bytes)
except ContentTooLargeError:
    # Content exceeds the policy max_size — return HTTP 413
    ...
except StorageError:
    # Unknown policy, backend failure, etc.
    ...
```

## Object keys and policy validation

Each write creates `{key_prefix}/{model}/{entity_id}/{field}/{uuid}{ext}`; the
UUID is new on every write, so replacing content never overwrites the previous
object and two fields of one entity never collide. Keys written by earlier
versions (`{model}/{id}/{id}{ext}`) stay readable because the stored
`location` is always used.

On read/delete the manager checks that `ref.backend` is the policy's backend
and that `ref.location` lies under the policy `key_prefix` or one of
`legacy_key_prefixes`. If you ever change a policy `key_prefix` on a
deployment with data, keep the old value so existing refs stay valid:

```python
StoragePolicy("documents", "local", key_prefix="docs_v2",
              legacy_key_prefixes=("docs",))
```

Other policy options: `allowed_content_types=("image/*", "application/pdf")`.
Client-supplied filenames are sanitized and content types validated; serve
stored files with `Content-Disposition: attachment` and `nosniff`.
`manager.get(ref, verify_checksum=True)` verifies the SHA-256 on read.

## Garbage Collection

```python
from granite_storage.gc import StorageGarbageCollector
from granite_storage.integrations.sqlalchemy import iter_model_storage_refs

with Session(engine) as session:
    gc = StorageGarbageCollector(
        manager=manager,
        iter_references=lambda: iter_model_storage_refs(session, Document, "_file_ref"),
    )
    # Dry run
    report = gc.collect(storage_key="documents", dry_run=True)
    print(f"Orphaned: {report.orphaned} / {report.scanned}")

    # Delete orphans
    report = gc.collect(storage_key="documents", dry_run=False)
    print(f"Deleted: {report.deleted}")
```

Safeguards: only objects older than `min_age` (default 24 h) are deleted, so
uploads whose transaction has not committed yet are safe; the policy must have a
`key_prefix`; `iter_references` must yield the references of **every** model
that uses the policy, and a real run aborts if it yields none while objects exist
(`force=True` overrides); delete errors are collected in `report.errors`.

## Alembic Migration Helper

```python
from alembic import op
import sqlalchemy as sa
from granite_storage import portable_storage_ref_type

def upgrade():
    op.add_column(
        "document",
        sa.Column("_file_ref", portable_storage_ref_type(), nullable=True),
    )
```

## Development

```bash
# Run tests
make test

# Run tests with coverage
make test-cov

# Lint and format
make lint
make format

# Type check
make type-check

# Build documentation
make docs

# Serve documentation locally (http://localhost:8000)
make docs-serve
```

## Documentation

Full documentation (API reference, user guide, SQLAlchemy integration, garbage collection,
and a guide for implementing custom backends) is available in `docs/` after running `make docs`,
or in the source files under `docs_source/`.

## License

MIT — see [LICENSE](LICENSE) for details.
