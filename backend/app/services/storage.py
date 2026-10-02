"""Object storage behind a small interface.

Production uses a private S3-compatible bucket (AWS S3, Cloudflare R2,
Backblaze B2...). Nothing in the bucket is public: every file is streamed
through an API endpoint that applies the right authorization (or, for public
site assets, none). The local backend exists only for development and tests.
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
        if self.root not in path.parents:
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


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra: dict[str, str] = {}
        # AWS S3 needs SSE requested explicitly; S3-compatible providers (R2, B2)
        # encrypt at rest already and some reject the header.
        if not get_settings().s3_endpoint_url:
            extra["ServerSideEncryption"] = "AES256"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise StoredObjectNotFound(key) from exc
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage()
    if settings.is_production:
        raise RuntimeError("Local file storage is not allowed in production.")
    return LocalStorage(settings.local_storage_dir)


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
