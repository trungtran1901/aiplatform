from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.repositories.workflow_run_repository import WorkflowRunRepository
from app.schemas.common import PaginatedResponse
from app.schemas.workflow_run import WorkflowEventRead, WorkflowRunRead, WorkflowRunStepRead
from app.services.workflow_run_service import WorkflowRunService

router = APIRouter(prefix="/workflow-runs", tags=["Workflow Runs"])


@router.get("", response_model=PaginatedResponse[WorkflowRunRead])
async def list_workflow_runs(
    workflow_id: UUID | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = WorkflowRunRepository(db)
    if workflow_id is not None:
        items, total = await repo.list_by_workflow(workflow_id, offset=pagination.offset, limit=pagination.limit)
    else:
        items, total = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[WorkflowRunRead](
        items=[WorkflowRunRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/{workflow_run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(workflow_run_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRunRepository(db)
    obj = await repo.get_or_404(workflow_run_id)
    return WorkflowRunRead.model_validate(obj)


@router.get("/{workflow_run_id}/steps", response_model=list[WorkflowRunStepRead])
async def get_workflow_run_steps(workflow_run_id: UUID, db: AsyncSession = Depends(get_db)):
    service = WorkflowRunService(db)
    steps = await service.list_steps(workflow_run_id)
    return [WorkflowRunStepRead.model_validate(s) for s in steps]


@router.get("/{workflow_run_id}/events", response_model=list[WorkflowEventRead])
async def get_workflow_run_events(workflow_run_id: UUID, db: AsyncSession = Depends(get_db)):
    service = WorkflowRunService(db)
    events = await service.list_events(workflow_run_id)
    return [WorkflowEventRead.model_validate(e) for e in events]
