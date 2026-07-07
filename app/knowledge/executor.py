"""
KnowledgeSkillExecutor.

Executes exactly one Knowledge Skill: load its `config`, build a search
request, forward auth headers, call the Knowledge Platform, parse the
response, and return LLM-ready context text. Mirrors the shape of
app/agno_runtime/workflow_runner.py::WorkflowRunner - a thin executor
that contains no orchestration logic of its own (that belongs to
KnowledgeSkillService), and is easily unit-testable by injecting a fake
KnowledgeClient.

Per docs/Knowledge.md's error-handling requirements, this class never
raises out of `execute()` for expected failure modes (service
unavailable, timeout, bad config) - it always returns a
KnowledgeExecutionResult so a Knowledge failure can never crash the
Agent run that requested it. Only truly unexpected exceptions escape,
and even those are logged first.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.logging import get_logger
from app.knowledge.client import KnowledgeClient
from app.knowledge.exceptions import KnowledgeConfigError, KnowledgeServiceError
from app.knowledge.mapper import parse_search_response, render_context
from app.knowledge.models import KnowledgeChunkSource, KnowledgeSkillConfig

logger = get_logger(__name__)


@dataclass
class KnowledgeExecutionResult:
    ok: bool
    context: str = ""
    chunk_count: int = 0
    latency_ms: int = 0
    error: str | None = None


class KnowledgeSkillExecutor:
    def __init__(self, config: KnowledgeSkillConfig, *, forward_headers: dict[str, str] | None = None) -> None:
        self.config = config
        self.client = KnowledgeClient(config, forward_headers=forward_headers)

    @classmethod
    def from_raw_config(cls, raw_config: dict, *, forward_headers: dict[str, str] | None = None) -> "KnowledgeSkillExecutor":
        try:
            config = KnowledgeSkillConfig.model_validate(raw_config or {})
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeConfigError(f"Invalid Knowledge Skill config: {exc}") from exc
        return cls(config, forward_headers=forward_headers)

    async def execute(self, query: str, *, skill_code: str = "") -> KnowledgeExecutionResult:
        """Runs one search and returns rendered context. Never raises -
        transport/config failures are captured into the result so the
        calling Agent run can continue without this Skill's context
        rather than failing entirely."""
        started = time.monotonic()
        try:
            raw = await self.client.search(query)
            result = parse_search_response(raw)
            context = render_context(result)
            latency_ms = int((time.monotonic() - started) * 1000)

            if result.chunk_count == 0:
                logger.warning(
                    "knowledge_zero_chunks_parsed",
                    skill_code=skill_code,
                    collection_id=self.config.collectionId,
                    raw_top_level_keys=list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
                )

            logger.info(
                "knowledge_skill_executed",
                skill_code=skill_code,
                collection_id=self.config.collectionId,
                chunk_count=result.chunk_count,
                latency_ms=latency_ms,
            )
            return KnowledgeExecutionResult(
                ok=True, context=context, chunk_count=result.chunk_count, latency_ms=latency_ms
            )
        except KnowledgeServiceError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "knowledge_skill_failed",
                skill_code=skill_code,
                error_code=exc.error_code,
                error=exc.message,
                latency_ms=latency_ms,
            )
            return KnowledgeExecutionResult(ok=False, latency_ms=latency_ms, error=exc.message)

    async def fetch_source(self, chunk_id: str, *, skill_code: str = "") -> KnowledgeChunkSource | None:
        """Resolves the original document location (document_id, page,
        bbox, source_url) for one previously-retrieved chunk_id, via
        GET {knowledgeBaseUrl}/chunks/{chunk_id}/source. Called
        on-demand (only when the user actually asks to see the source
        document), never eagerly for every retrieved chunk. Returns None
        - never raises - on any failure, so a bad/expired chunk_id or a
        Knowledge Platform hiccup degrades to "source unavailable"
        rather than breaking the run.
        """
        try:
            raw = await self.client.get_chunk_source(chunk_id)
            return KnowledgeChunkSource.model_validate(raw)
        except KnowledgeServiceError as exc:
            logger.warning(
                "knowledge_source_fetch_failed",
                skill_code=skill_code,
                chunk_id=chunk_id,
                error_code=exc.error_code,
                error=exc.message,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "knowledge_source_parse_failed", skill_code=skill_code, chunk_id=chunk_id, error=str(exc)
            )
            return None