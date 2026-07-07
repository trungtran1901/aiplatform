"""
Knowledge Platform HTTP client.

Pure transport. Contains no retrieval/ranking/parsing logic of its own -
it POSTs a search request built entirely from KnowledgeSkillConfig +
the caller's query, and returns the raw decoded JSON body. Response
shaping into KnowledgeSearchResult happens in mapper.py, kept separate
so this client stays a thin, easily-mockable HTTP boundary.

AUTH: exactly like app/agno_runtime/mcp_client.py's contract with MCP
Gateway - whatever Authorization / X-API-Key headers were captured off
the inbound chat request (app/core/auth_context.py) are forwarded
verbatim. This client never generates, validates, or decodes a token;
the Knowledge Platform is solely responsible for authenticating the
forwarded credential, exactly as MCP Gateway is for its own calls.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.knowledge.exceptions import KnowledgeTimeoutError, KnowledgeUnavailableError
from app.knowledge.models import KnowledgeSkillConfig

logger = get_logger(__name__)


class KnowledgeClient:
    def __init__(self, config: KnowledgeSkillConfig, *, forward_headers: dict[str, str] | None = None) -> None:
        self.config = config
        self.forward_headers = forward_headers or {}

    async def search(self, query: str) -> dict[str, Any]:
        """POSTs {knowledgeBaseUrl}{searchApi} with a body built entirely
        from `config` plus the caller-supplied `query`, and returns the
        decoded JSON response body.

        Raises KnowledgeTimeoutError / KnowledgeUnavailableError on
        transport failure - never raises on a well-formed-but-empty
        result set (zero chunks is a valid, non-error response).
        """
        body = {
            "query": query,
            "collectionId": self.config.collectionId,
            "topK": self.config.topK,
        }
        if self.config.agentId:
            body["agentId"] = self.config.agentId
        if self.config.embeddingModelCode:
            body["embeddingModelCode"] = self.config.embeddingModelCode

        headers = {"Content-Type": "application/json", **self.forward_headers}

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(self.config.search_url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            logger.warning(
                "knowledge_search_timeout",
                url=self.config.search_url,
                collection_id=self.config.collectionId,
                timeout=self.config.timeout,
            )
            raise KnowledgeTimeoutError(
                f"Knowledge Platform did not respond within {self.config.timeout}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "knowledge_search_http_error",
                url=self.config.search_url,
                status_code=exc.response.status_code,
            )
            raise KnowledgeUnavailableError(
                f"Knowledge Platform returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("knowledge_search_transport_error", url=self.config.search_url, error=str(exc))
            raise KnowledgeUnavailableError(f"Failed to reach Knowledge Platform: {exc}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "knowledge_search_completed",
            url=self.config.search_url,
            collection_id=self.config.collectionId,
            latency_ms=elapsed_ms,
        )
        return data

    async def get_chunk_source(self, chunk_id: str) -> dict[str, Any]:
        """GETs {knowledgeBaseUrl}{sourceApi} for one chunk_id and
        returns the decoded JSON body (document_id, page, bbox,
        source_url). Same auth-forwarding and error-mapping contract as
        search() above - the caller's Authorization / X-API-Key header
        is forwarded verbatim, never generated or validated here."""
        url = self.config.source_url(chunk_id)
        headers = {"Accept": "application/json", **self.forward_headers}

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("knowledge_source_timeout", url=url, chunk_id=chunk_id, timeout=self.config.timeout)
            raise KnowledgeTimeoutError(
                f"Knowledge Platform did not respond within {self.config.timeout}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("knowledge_source_http_error", url=url, chunk_id=chunk_id, status_code=exc.response.status_code)
            raise KnowledgeUnavailableError(
                f"Knowledge Platform returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("knowledge_source_transport_error", url=url, chunk_id=chunk_id, error=str(exc))
            raise KnowledgeUnavailableError(f"Failed to reach Knowledge Platform: {exc}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info("knowledge_source_completed", url=url, chunk_id=chunk_id, latency_ms=elapsed_ms)
        return data