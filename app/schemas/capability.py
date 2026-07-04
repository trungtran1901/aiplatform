from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class CapabilityLevel(str, Enum):
    agent_os = "agent_os"
    team = "team"
    agent = "agent"


class CapabilityAssignmentCreate(BaseModel):
    level: CapabilityLevel
    target_id: UUID = Field(..., description="ID of the AgentOS, Team, or Agent being assigned to")
    capability_codes: list[str] = Field(..., min_length=1)


class CapabilityAssignmentRead(BaseModel):
    level: CapabilityLevel
    target_id: UUID
    capability_codes: list[str]


class CapabilityResolutionRequest(BaseModel):
    agent_os_id: UUID
    team_id: UUID
    agent_id: UUID


class CapabilityResolutionResult(BaseModel):
    agent_os_capabilities: list[str]
    team_capabilities: list[str]
    agent_capabilities: list[str]
    effective_capabilities: list[str] = Field(
        ..., description="intersection(agent_os, team, agent) - the actual allowed tool set"
    )
