"""Execution Engine API - AgentX v2 Phase 8+9, flagged.

POST /execution-plans/run builds an ExecutionPlan (Planning Engine) from
the request body and immediately executes it (Execution Engine) -
combined into one endpoint since a Plan is ad-hoc/non-persisted by
design (unlike Workflow, which is saved metadata executed later via
POST /workflows/{id}/run).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.execution.service import ExecutionEngineService
from app.planning.service import PlanningEngineService
from app.schemas.execution_plan import ExecutionPlanRunRequest, ExecutionPlanRunResponse

router = APIRouter(prefix="/execution-plans", tags=["Planning + Execution Engine (v2, flagged)"])


def _require_enabled() -> None:
    settings = get_settings()
    if not (settings.FEATURE_PLANNING_ENGINE and settings.FEATURE_EXECUTION_ENGINE):
        raise NotFoundError("Planning/Execution Engine is not enabled on this deployment")


@router.post("/run", response_model=ExecutionPlanRunResponse)
async def run_execution_plan(payload: ExecutionPlanRunRequest, db: AsyncSession = Depends(get_db)):
    _require_enabled()

    planner = PlanningEngineService()
    plan = planner.build_plan(
        payload.message,
        agent_os_code=payload.agentOs,
        team_code=None,
        agent_code=None,
        explicit_steps=[s.model_dump() for s in payload.steps] if payload.steps else None,
    )

    executor = ExecutionEngineService(db)
    session_id = str(payload.session_id) if payload.session_id else str(uuid.uuid4())
    result = await executor.run_plan(plan, session_id=session_id, user_id=payload.user_id)
    return ExecutionPlanRunResponse(**result)
