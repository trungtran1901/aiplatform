from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.repositories.capability_repository import CapabilityRepository
from app.schemas.capability import (
    CapabilityAssignmentCreate,
    CapabilityAssignmentRead,
    CapabilityLevel,
    CapabilityResolutionRequest,
    CapabilityResolutionResult,
)
from app.services.capability_service import CapabilityService

router = APIRouter(prefix="/capabilities", tags=["Capabilities"])

_SETTERS = {
    CapabilityLevel.agent_os: "set_agent_os_capabilities",
    CapabilityLevel.team: "set_team_capabilities",
    CapabilityLevel.agent: "set_agent_capabilities",
}
_GETTERS = {
    CapabilityLevel.agent_os: "get_agent_os_capabilities",
    CapabilityLevel.team: "get_team_capabilities",
    CapabilityLevel.agent: "get_agent_capabilities",
}


@router.get("/assignments", response_model=CapabilityAssignmentRead)
async def get_assignment(
    level: CapabilityLevel,
    target_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    repo = CapabilityRepository(db)
    getter = getattr(repo, _GETTERS[level])
    codes = await getter(target_id)
    return CapabilityAssignmentRead(level=level, target_id=target_id, capability_codes=codes)


@router.post(
    "/assignments",
    response_model=CapabilityAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def set_assignment(payload: CapabilityAssignmentCreate, db: AsyncSession = Depends(get_db)):
    repo = CapabilityRepository(db)
    setter = getattr(repo, _SETTERS[payload.level])
    await setter(payload.target_id, payload.capability_codes)
    return CapabilityAssignmentRead(
        level=payload.level, target_id=payload.target_id, capability_codes=payload.capability_codes
    )


@router.post("/resolve", response_model=CapabilityResolutionResult)
async def resolve_capabilities(payload: CapabilityResolutionRequest, db: AsyncSession = Depends(get_db)):
    """Computes intersection(agent_os_capabilities, team_capabilities,
    agent_capabilities) - useful for the Quasar Admin UI to preview the
    effective tool set before saving an assignment."""
    service = CapabilityService(db)
    return await service.resolve(payload.agent_os_id, payload.team_id, payload.agent_id)
