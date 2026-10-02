"""Persistent local file storage backed by Render's paid persistent disk.

The database stores file metadata while this service stores file bytes under the
configured persistent mount path. Because Render disks attach to one instance,
the API is intentionally deployed as a single instance.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger("kiowa.storage")


class StoredObjectNotFound(Exception):
    pass


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StoredObjectNotFound(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    return LocalStorage(get_settings().local_storage_dir)


def new_key(prefix: str, extension: str) -> str:
    """Storage keys never contain user-supplied filenames."""
    return f"{prefix}/{uuid.uuid4().hex}{extension}"


def delete_quietly(key: str | None) -> None:
    """Best-effort delete of a replaced/removed object; failures are logged, not raised."""
    if not key:
        return
    try:
        get_storage().delete(key)
    except Exception:  # noqa: BLE001 - an orphaned object must not fail the user's request
        logger.exception("storage_delete_failed", extra={"storage_key": key})
