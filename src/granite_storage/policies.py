from dataclasses import dataclass


@dataclass(frozen=True)
class StoragePolicy:
    storage_key: str
    backend_key: str
    max_size: int | None = None
    key_prefix: str | None = None
