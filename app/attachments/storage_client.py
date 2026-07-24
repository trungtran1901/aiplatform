"""MinIO storage client - pure transport, không có logic OCR/business ở đây."""
from __future__ import annotations

import io
import uuid

from minio import Minio

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Minio(
            settings.MINIO_ENDPOINT.replace("http://", "").replace("https://", ""),
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


class MinioStorageClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = _get_client()
        self.bucket = self.settings.MINIO_BUCKET
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload(self, file_bytes: bytes, *, filename: str, content_type: str) -> str:
        """Upload và trả về storage_key (object name trong bucket)."""
        key = f"attachments/{uuid.uuid4()}/{filename}"
        self.client.put_object(
            self.bucket, key, io.BytesIO(file_bytes), length=len(file_bytes), content_type=content_type
        )
        logger.info("attachment_uploaded_to_minio", key=key, size=len(file_bytes))
        return key

    def download(self, storage_key: str) -> bytes:
        response = self.client.get_object(self.bucket, storage_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def presigned_url(self, storage_key: str, *, expires_seconds: int = 3600) -> str:
        from datetime import timedelta
        return self.client.presigned_get_object(self.bucket, storage_key, expires=timedelta(seconds=expires_seconds))