"""Client cho dịch vụ OCR nội bộ - thuần transport, forward file bytes,
parse response thành text phẳng để fold vào prompt."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OCRServiceError(Exception):
    pass


class OCRClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.OCR_SERVICE_URL.rstrip("/")
        self.timeout = settings.OCR_TIMEOUT_SECONDS

    async def _post_file(self, path: str, file_bytes: bytes, *, filename: str, content_type: str, params: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    params=params or {},
                    files={"file": (filename, file_bytes, content_type)},
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            logger.error("ocr_service_call_failed", path=path, error=str(exc))
            raise OCRServiceError(f"OCR service call failed ({path}): {exc}") from exc

    async def ocr_image(self, file_bytes: bytes, *, filename: str, content_type: str = "image/png") -> dict:
        return await self._post_file(
            "/ocr/image", file_bytes, filename=filename, content_type=content_type,   # dùng tham số truyền vào
            params={"preprocess": "false", "normalize_method": "dpi", "target_dpi": 300,
                    "target_text_height": 30, "bbox_format": "xyxy", "save_preprocessed": "false"},
        )

    async def ocr_pdf(self, file_bytes: bytes, *, filename: str) -> dict:
        return await self._post_file(
            "/ocr/pdf", file_bytes, filename=filename, content_type="application/pdf",
            params={"preprocess": "false", "normalize_method": "dpi", "target_dpi": 300,
                    "target_text_height": 30, "bbox_format": "xyxy"},
        )

    async def detect_table(self, file_bytes: bytes, *, filename: str, content_type: str) -> dict:
        return await self._post_file(
            "/table/detect", file_bytes, filename=filename, content_type=content_type,
            params={"threshold": 0.5, "tsr_threshold": 0.3},
        )

    async def detect_layout(self, file_bytes: bytes, *, filename: str, content_type: str) -> dict:
        return await self._post_file(
            "/layout/detect", file_bytes, filename=filename, content_type=content_type,
            params={"threshold": 0.5},
        )