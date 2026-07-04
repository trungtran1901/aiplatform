"""Shared response-model presenters for Skill, used by both
app/api/v1/skills.py and app/api/v1/agents.py (GET /agents/{id}/skills) -
kept in its own module rather than imported router-to-router, to avoid a
circular import between the two route modules.
"""
from __future__ import annotations

from app.repositories.skill_repository import SkillRepository
from app.schemas.skill import SkillRead


async def skill_to_read_model(repo: SkillRepository, obj) -> SkillRead:
    codes = await repo.get_capability_codes(obj.id)
    data = SkillRead.model_validate(obj).model_dump()
    data["capability_codes"] = codes
    return SkillRead.model_validate(data)
