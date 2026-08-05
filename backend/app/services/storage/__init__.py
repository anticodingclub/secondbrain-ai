"""Object storage: local disk today, S3 later, one interface."""

from app.core.config import Settings, StorageBackend
from app.services.storage.base import ObjectStorage, StoredObject
from app.services.storage.local import LocalObjectStorage, sanitize_extension

__all__ = [
    "LocalObjectStorage",
    "ObjectStorage",
    "StoredObject",
    "build_object_storage",
    "sanitize_extension",
]


def build_object_storage(settings: Settings) -> ObjectStorage:
    """Pick a storage backend from configuration.

    S3 is deliberately not stubbed out here: an unimplemented branch that
    raises at runtime is worse than an honest failure at startup, and the
    interface is the part that had to exist now.
    """
    match settings.storage_backend:
        case StorageBackend.LOCAL:
            return LocalObjectStorage(settings.storage_path)
        case unsupported:  # pragma: no cover - guarded by the settings enum
            raise NotImplementedError(f"Storage backend {unsupported!r} is not built yet.")
