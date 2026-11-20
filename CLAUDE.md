# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**granite-storage** is a lightweight, backend-agnostic storage abstraction for SQLAlchemy 2 models. It decouples physical file storage (local filesystem, S3) from ORM models, with streaming uploads, size-limit enforcement, and orphan garbage collection. Ships as a PyPI package (`src/` layout), targets Python 3.12+.

## Commands

Dependency management uses `uv`; all commands are wrapped in the `makefile`.

```bash
make install          # uv sync
make test              # uv run pytest -v
make test-cov          # pytest with coverage (xml + term + html)
make lint               # ruff check src/ tests/
make format             # ruff format .
make type-check          # mypy src/ (strict mode)
make security-check      # bandit -r src/
make check                # lint + format + type-check + security-check
make docs                  # sphinx-build docs_source docs
make docs-serve             # build + serve docs at localhost:8000
```

Run a single test: `uv run pytest tests/test_manager.py::test_name -v`

CI (`.github/workflows/release.yml`) runs `pytest tests/ --cov=src/ --cov-report=term --cov-fail-under=80` on every push to `main`, then builds and auto-publishes to PyPI — **coverage must stay ≥80%**.

Tests that exercise S3 use `moto` to mock AWS; no real credentials/bucket needed. FastAPI is an optional dependency — `mixin.py` degrades gracefully (`UploadFile` import is wrapped in try/except) when it's absent.

## Architecture

Everything lives in `src/granite_storage/`. Data flows: **Mixin → Manager → Policy → Backend**.

- **`contracts.py`** — `StorageBackend` Protocol. Any backend (local, S3, or a custom one) must implement `put_bytes`, `put_stream`, `get`, `open`, `delete`, `exists`, `iter_locations`.
- **`backends/local.py`, `backends/s3.py`** — concrete backends. Local resolves paths under a root dir and guards against path traversal (`_resolve_path`). S3 wraps boto3, prefixes keys, and translates `ClientError` into `StorageError`.
- **`policies.py`** — `StoragePolicy` (frozen dataclass): maps a `storage_key` to a `backend_key`, plus optional `max_size` and `key_prefix`.
- **`manager.py`** — `StorageManager` is the central orchestrator. Holds `{backend_key: StorageBackend}` and `{storage_key: StoragePolicy}` dicts, resolves policy → backend, builds the storage object key via `utils.build_storage_object_key` (layout: `{model_name}/{uuid}/{uuid}{ext}`), and enforces `max_size` — for byte payloads directly, for streams via `SizeLimitedStream` (a streaming `BinaryIO` wrapper that raises `ContentTooLargeError` once the cumulative read exceeds the limit).
- **`models.py`** — `StoredObjectRef`: the dataclass persisted as JSON in the DB row (storage_key, backend, location, size, checksum, content_type, original_filename, created_at, extra). This is the only artifact that crosses the storage/DB boundary. `to_uri()` builds `s3://` or `file://` URIs.
- **`mixin.py`** — `StoredContentMixin`: attach to a SQLAlchemy model to get `set_content()`, `set_content_from_stream()`, `set_content_from_uploadfile()` (FastAPI), `get_content()`, `open_content()`, `replace_content()`, `clear_content_reference()`. Requires the model to define `__stored_content_field_name__`, `__stored_content_storage_key__`, and to call `configure_storage_manager()` once at startup (manager is a classvar shared across instances). Content operations require the entity to already have an `id` (flush before storing).
- **`types.py`** — `StoredObjectRefType`, a SQLAlchemy `TypeDecorator` (JSON, JSONB on Postgres) that (de)serializes `StoredObjectRef` transparently at the ORM layer.
- **`gc.py`** — `StorageGarbageCollector`: given an `iter_references` callable (typically `integrations.sqlalchemy.iter_model_storage_refs`) and a `storage_key`, diffs backend `iter_locations()` against DB-referenced locations to find/delete orphans. Supports `dry_run`.
- **`integrations/sqlalchemy.py`** — glue for wiring GC to SQLAlchemy sessions.
- **`alembic_helpers.py`** — `portable_storage_ref_type()` for use in Alembic migrations, independent of the mixin/manager runtime.

### Key invariants

- `StoredObjectRef.storage_key` is set by `StorageManager`, not by backends — backends know nothing about policies.
- Backends never enforce `max_size`; only `StorageManager` does (pre-check for bytes, streaming check for streams).
- `clear_content_reference()` only detaches the DB reference — it does **not** delete the physical object; GC or explicit `manager.delete()` handles that.
- Object key layout (`{model_name}/{uuid}/{uuid}{ext}`) is intentional (see `utils.build_storage_object_key` docstring) — it's designed so a single CloudFront/signed-URL policy can cover a file plus future derivatives.
