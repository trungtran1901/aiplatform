from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.models.workflow import Workflow
from app.schemas.common import PaginatedResponse
from app.schemas.workflow import WorkflowCreate, WorkflowDetail, WorkflowRead, WorkflowStepRead, WorkflowUpdate
from app.schemas.workflow_run import WorkflowRunRequest, WorkflowRunResponse
from app.services.workflow_execution_service import WorkflowExecutionService
from app.services.workflow_registry import WorkflowRegistry

router = APIRouter(prefix="/workflows", tags=["Workflows"])


def _to_detail(workflow: Workflow) -> WorkflowDetail:
    data = WorkflowRead.model_validate(workflow).model_dump()
    data["steps"] = [WorkflowStepRead.model_validate(s) for s in workflow.steps]
    return WorkflowDetail.model_validate(data)


@router.get("", response_model=PaginatedResponse[WorkflowRead])
async def list_workflows(
    agent_os_id: UUID | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    registry = WorkflowRegistry(db)
    items, total = await registry.list_workflows(
        agent_os_id=agent_os_id, offset=pagination.offset, limit=pagination.limit
    )
    return PaginatedResponse[WorkflowRead](
        items=[WorkflowRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=WorkflowDetail, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: WorkflowCreate, db: AsyncSession = Depends(get_db)):
    registry = WorkflowRegistry(db)
    workflow = await registry.create_workflow(payload)
    return _to_detail(workflow)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(workflow_id: UUID, db: AsyncSession = Depends(get_db)):
    registry = WorkflowRegistry(db)
    workflow = await registry.get_workflow(workflow_id)
    return _to_detail(workflow)


@router.put("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(workflow_id: UUID, payload: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    registry = WorkflowRegistry(db)
    workflow = await registry.update_workflow(workflow_id, payload)
    return _to_detail(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, db: AsyncSession = Depends(get_db)):
    registry = WorkflowRegistry(db)
    await registry.delete_workflow(workflow_id)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(workflow_id: UUID, payload: WorkflowRunRequest, db: AsyncSession = Depends(get_db)):
    """
    Executes a Workflow's steps sequentially (AGENT/TEAM only - no
    branching, loops, parallel execution, or approval steps in Phase 1).
    Each step's output becomes the next step's input. Any inbound
    Authorization / X-API-Key header is forwarded unchanged to MCP
    Gateway on every tool call made by any step's underlying Agent/Team
    run - this endpoint performs no authorization of its own, exactly
    like POST /api/v1/chat.
    """
    service = WorkflowExecutionService(db)
    result = await service.run_workflow(workflow_id, payload)
    return WorkflowRunResponse(**result)


@router.post("/{workflow_id}/run/stream")
async def run_workflow_stream(workflow_id: UUID, payload: WorkflowRunRequest, db: AsyncSession = Depends(get_db)):
    """Streaming workflow execution via SSE. Emits WorkflowStarted,
    WorkflowStepStarted, WorkflowStep:<inner event>, WorkflowStepCompleted,
    WorkflowCompleted, WorkflowFailed."""
    service = WorkflowExecutionService(db)

    async def event_generator():
        async for event in service.run_workflow_stream(workflow_id, payload):
            yield {
                "event": event["event_type"],
                "data": json.dumps({"workflow_run_id": str(event["workflow_run_id"]), "data": event["data"]}),
            }

    return EventSourceResponse(event_generator())
