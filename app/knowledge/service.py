"""
KnowledgeSkillService.

High-level orchestration layer used by both:
  - AgnoRuntimeEngine (app/agno_runtime/engine.py), to fold Knowledge
    context into an Agent's prompt before a chat turn, and
  - POST /api/v1/skills/{id}/test (app/api/v1/skills.py), to let the
    future Admin UI test a Knowledge Skill's configuration live.

Neither caller talks to KnowledgeClient/KnowledgeSkillExecutor directly -
this is the single place that knows how to go from a Skill id to a
result, keeping the "load skill -> validate type -> forward auth ->
execute" sequence in one place.
"""
from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import get_propagated_auth
from app.core.logging import get_logger
from app.knowledge.exceptions import KnowledgeConfigError
from app.knowledge.executor import KnowledgeExecutionResult, KnowledgeSkillExecutor
from app.models.skill import Skill, SkillType
from app.repositories.skill_repository import SkillRepository

logger = get_logger(__name__)


class KnowledgeSkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skill_repo = SkillRepository(session)

    def _forward_headers(self) -> dict[str, str]:
        """Forwards whatever inbound Authorization / X-API-Key headers
        were captured for this request - see app/core/auth_context.py.
        Never generates or validates credentials, exactly like
        app/agno_runtime/mcp_client.py's contract with MCP Gateway."""
        return get_propagated_auth().as_forward_headers()

    def _build_executor(self, skill: Skill) -> KnowledgeSkillExecutor:
        if skill.skill_type != SkillType.knowledge:
            raise KnowledgeConfigError(
                f"Skill '{skill.code}' is not a KNOWLEDGE skill (skill_type={skill.skill_type.value})"
            )
        return KnowledgeSkillExecutor.from_raw_config(skill.config, forward_headers=self._forward_headers())

    async def execute_by_skill(self, skill: Skill, query: str) -> KnowledgeExecutionResult:
        """Executes a Knowledge Skill that the caller has already loaded
        (used by the runtime engine, which loads Skills in bulk per
        agent rather than one at a time)."""
        try:
            executor = self._build_executor(skill)
        except KnowledgeConfigError as exc:
            logger.warning("knowledge_skill_config_invalid", skill_code=skill.code, error=str(exc))
            return KnowledgeExecutionResult(ok=False, error=exc.message)
        return await executor.execute(query, skill_code=skill.code)

    async def execute_by_id(self, skill_id: uuid.UUID, query: str) -> KnowledgeExecutionResult:
        """Executes a Knowledge Skill by id - used by
        POST /api/v1/skills/{id}/test."""
        skill = await self.skill_repo.get_or_404(skill_id)
        return await self.execute_by_skill(skill, query)

    async def execute_for_agent(self, agent_id: uuid.UUID, query: str) -> str:
        """Executes every KNOWLEDGE-type skill assigned to an Agent
        (Skill has no enabled/disabled flag of its own - unassign it via
        /skills/unassign to stop using it) and concatenates their
        rendered contexts, in the order the skills were assigned. Used by AgnoRuntimeEngine to build the
        "Knowledge Context" block folded into the Agent's instructions
        before a run (see docs/Knowledge.md "Agent Configuration") - the
        Agent itself never sees collectionId/knowledgeBaseUrl/etc., only
        the resulting text.

        A single Knowledge Skill failing (timeout, service down, bad
        config) never aborts the others or the Agent run - it is simply
        omitted, matching the "Never crash Agent execution" requirement.
        """
        skills = await self.skill_repo.list_skills_for_agent(agent_id)
        knowledge_skills = [s for s in skills if s.skill_type == SkillType.knowledge]
        if not knowledge_skills:
            return ""

        contexts: list[str] = []
        for skill in knowledge_skills:
            result = await self.execute_by_skill(skill, query)
            if result.ok and result.context:
                contexts.append(result.context)

        return "\n\n".join(contexts)

    async def build_source_lookup_tool(self, agent_id: uuid.UUID) -> Callable | None:
        """Builds a callable tool the Agent can invoke on demand to
        resolve the original document (source_url + page) for a
        chunk_id it saw in its Knowledge Context - see
        app/knowledge/mapper.py::render_context, which tells the LLM to
        call exactly this tool by name ("get_document_source") instead
        of fabricating a document link.

        Returns None when the Agent has no KNOWLEDGE skills assigned,
        so callers can simply omit the tool rather than register a
        no-op. When an Agent has more than one KNOWLEDGE skill, the
        returned tool tries each one's configured Knowledge Platform in
        turn and returns the first successful resolution - a chunk_id
        is only ever valid against the Knowledge Platform instance that
        produced it, so trying each is the only way to disambiguate
        without threading extra state through the LLM's tool call.
        """
        skills = await self.skill_repo.list_skills_for_agent(agent_id)
        knowledge_skills = [s for s in skills if s.skill_type == SkillType.knowledge]
        if not knowledge_skills:
            return None

        forward_headers = self._forward_headers()
        executors: list[KnowledgeSkillExecutor] = []
        for skill in knowledge_skills:
            try:
                executors.append(
                    KnowledgeSkillExecutor.from_raw_config(skill.config, forward_headers=forward_headers)
                )
            except KnowledgeConfigError:
                continue

        if not executors:
            return None

        async def get_document_source(chunk_id: str) -> str:
            """Retrieve the original source document location (URL and page number)
            for a knowledge chunk, identified by its chunk_id. Call this only when
            the user explicitly asks to see, open, or download the source document
            for information you previously answered with. Never fabricate a document
            link yourself - always call this tool to get the real one."""
            for executor in executors:
                source = await executor.fetch_source(chunk_id)
                if source is not None:
                    page_info = f" (trang {source.page})" if source.page is not None else ""
                    return f"Tài liệu gốc{page_info}: {source.source_url}"
            return "Không tìm thấy tài liệu gốc cho đoạn này."

        return get_document_source