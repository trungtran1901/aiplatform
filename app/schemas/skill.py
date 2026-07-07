from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.skill import SkillType
from app.schemas.common import TimestampedSchema


class SkillBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None
    skill_type: SkillType = Field(
        default=SkillType.mcp,
        description="Which Executor this Skill dispatches to. Defaults to MCP for "
        "backward compatibility with existing capability-bundle Skills.",
    )
    config: dict | None = Field(
        default=None,
        description="Executor-specific configuration. Required (and validated) for "
        "skill_type=KNOWLEDGE - see KnowledgeSkillConfig. Ignored for skill_type=MCP.",
    )


class SkillCreate(SkillBase):
    capability_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "SkillCreate":
        if self.skill_type == SkillType.knowledge:
            if not self.config:
                raise ValueError("config is required when skill_type=KNOWLEDGE")
            # Deferred import avoids a hard dependency from the generic
            # schemas package on the knowledge package for every other
            # skill type.
            from app.knowledge.models import KnowledgeSkillConfig

            KnowledgeSkillConfig.model_validate(self.config)
        if self.capability_codes and self.skill_type != SkillType.mcp:
            raise ValueError("capability_codes is only meaningful for skill_type=MCP")
        return self


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    config: dict | None = None
    capability_codes: list[str] | None = None


class SkillRead(TimestampedSchema, SkillBase):
    capability_codes: list[str] = Field(default_factory=list)


class AgentSkillAssign(BaseModel):
    agent_id: UUID
    skill_id: UUID


class SkillTestRequest(BaseModel):
    """Body for POST /api/v1/skills/{id}/test - currently only meaningful
    for skill_type=KNOWLEDGE (runs a live search against the configured
    Knowledge Platform instance and returns the retrieved chunks)."""

    query: str = Field(..., min_length=1)


class SkillTestResponse(BaseModel):
    skill_id: UUID
    skill_code: str
    ok: bool
    context: str | None = None
    chunk_count: int = 0
    latency_ms: int | None = None
    error: str | None = None
