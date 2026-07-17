"""
BusinessObjectSkillService.

build_lookup_tool(agent_id) / build_validate_tool(agent_id) each return
a callable the Agent can invoke by name, ONLY if the Agent has a Skill
assigned with config={"businessObjectLookup": true} - this is what makes
both tools selective per-Agent (unlike the Context Engine's UI Metadata
fold-in, which is the same for every Agent). Returns None otherwise,
exactly like KnowledgeSkillService.build_source_lookup_tool does when an
Agent has no Knowledge skills - callers can always safely omit an
unavailable tool.

lookup_business_object  -> read-only: fields/relationships/validation/meaning
validate_business_object -> runs payload.validation rules (see
                             app.businessobjects.validator) against a
                             caller-submitted record BEFORE the Agent
                             calls any MCP capability that would
                             actually persist the data (Path A) or before
                             it proposes UI actions to fill a form
                             (Path B) - either path benefits from
                             catching an invalid record before acting.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.businessobjects.validator import validate_record
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories.business_object_repository import BusinessObjectRepository
from app.repositories.skill_repository import SkillRepository

logger = get_logger(__name__)

_MARKER_CONFIG_KEY = "businessObjectLookup"


class BusinessObjectSkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skill_repo = SkillRepository(session)
        self.bo_repo = BusinessObjectRepository(session)

    async def _is_enabled_for_agent(self, agent_id: uuid.UUID) -> bool:
        if not get_settings().FEATURE_BUSINESS_OBJECT_REGISTRY:
            return False
        skills = await self.skill_repo.list_skills_for_agent(agent_id)
        return any(isinstance(s.config, dict) and s.config.get(_MARKER_CONFIG_KEY) for s in skills)

    async def build_lookup_tool(self, agent_id: uuid.UUID) -> Callable | None:
        if not await self._is_enabled_for_agent(agent_id):
            return None

        async def lookup_business_object(code: str) -> str:
            """Look up a Business Object's definition by its code -
            fields, relationships, validation rules, and business
            meaning. Call this whenever you need to know what a
            business entity (e.g. 'leave_request', 'employee',
            'invoice') looks like, which fields are required, or how it
            relates to other entities - never guess a business object's
            shape from conversation alone."""
            bo = await self.bo_repo.get_latest(code)
            if bo is None:
                return f"Không tìm thấy Business Object với code='{code}'."

            payload = bo.payload
            lines = [f"Business Object: {bo.name} (code={bo.code}, version={bo.version})"]
            if payload.get("businessMeaning"):
                lines.append(f"Ý nghĩa: {payload['businessMeaning']}")

            fields = payload.get("fields", [])
            if fields:
                lines.append("Fields:")
                for f in fields:
                    req = "bắt buộc" if f.get("required") else "không bắt buộc"
                    lines.append(f"  - {f['name']} ({f['type']}, {req})")

            relationships = payload.get("relationships", [])
            if relationships:
                lines.append("Relationships:")
                for r in relationships:
                    lines.append(f"  - {r['name']} -> {r['targetObjectCode']} ({r['cardinality']})")

            validation = payload.get("validation", [])
            if validation:
                lines.append("Validation rules:")
                for v in validation:
                    lines.append(f"  - {v.get('rule')}: {v.get('message', '')}")

            logger.info("business_object_looked_up", code=code, version=bo.version)
            return "\n".join(lines)

        return lookup_business_object

    async def build_validate_tool(self, agent_id: uuid.UUID) -> Callable | None:
        if not await self._is_enabled_for_agent(agent_id):
            return None

        async def validate_business_object(code: str, record_json: str) -> str:
            """Validate a proposed record against a Business Object's
            required fields and validation rules BEFORE creating it via
            any MCP tool or filling it into a UI form. `record_json`
            must be a JSON object string mapping field name -> value
            (e.g. '{"days": 3, "startDate": "2026-07-15", "endDate":
            "2026-07-17"}'). Always call this before calling a create/
            submit tool for a business object you looked up - never
            skip validation and assume the record is correct."""
            bo = await self.bo_repo.get_latest(code)
            if bo is None:
                return f"Không tìm thấy Business Object với code='{code}'."

            try:
                record = json.loads(record_json)
            except (TypeError, ValueError) as exc:
                return f"record_json không phải JSON hợp lệ: {exc}"

            violations = validate_record(bo.payload, record)
            if not violations:
                logger.info("business_object_validated_ok", code=code)
                return "Hợp lệ - record thỏa mãn mọi field bắt buộc và validation rule."

            logger.info("business_object_validation_failed", code=code, violation_count=len(violations))
            return "Không hợp lệ:\n" + "\n".join(f"- {v}" for v in violations)

        return validate_business_object