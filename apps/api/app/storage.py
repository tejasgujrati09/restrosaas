"""Private object storage for uploaded files. One small interface; the only implementation talks
S3, so MinIO in development and AWS S3 later differ by configuration alone. Objects are never
served to browsers: the API reads them and the worker deletes them once extraction is done."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class S3Storage:
    def __init__(self) -> None:
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3},
                connect_timeout=5,
                read_timeout=30,
            ),
        )
        self._bucket = settings.storage_bucket
        self._ready = False

    def _ensure_bucket(self) -> None:
        if self._ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)
        self._ready = True

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def _get(self, key: str) -> bytes:
        body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        return body

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, data, content_type)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)


class MemoryStorage:
    """For tests: same interface, nothing on the network."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage


def set_storage(storage: ObjectStorage | None) -> None:
    global _storage
    _storage = storage
