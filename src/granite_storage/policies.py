from __future__ import annotations

from dataclasses import dataclass

from granite_storage.utils import validate_storage_key


@dataclass(frozen=True)
class StoragePolicy:
    """Maps a ``storage_key`` to a backend plus limits and key layout.

    Attributes:
        storage_key: policy name stored in every reference.
        backend_key: key of the backend in ``StorageManager.backends``.
        max_size: maximum object size in bytes (``None`` = unlimited).
        key_prefix: prefix under which every object of this policy is
            written. When set, references whose ``location`` is outside it
            are rejected on read/delete (see ``legacy_key_prefixes``).
        legacy_key_prefixes: additional prefixes under which references
            created by earlier versions or configurations may live. They are
            accepted for reading/deleting and scanned by the garbage
            collector, but never used for new writes. Use this when you
            change ``key_prefix`` on a deployment that already has data.
    """

    storage_key: str
    backend_key: str
    max_size: int | None = None
    key_prefix: str | None = None
    legacy_key_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for prefix in (self.key_prefix, *self.legacy_key_prefixes):
            if prefix:
                validate_storage_key(prefix, is_prefix=True)

    @property
    def read_prefixes(self) -> tuple[str, ...]:
        """Every prefix a valid reference of this policy may live under."""
        return tuple(
            p.rstrip("/") for p in (self.key_prefix, *self.legacy_key_prefixes) if p
        )
