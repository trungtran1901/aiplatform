"""Workflow Schedule API - flagged behind FEATURE_WORKFLOW_SCHEDULING.
Nested under /workflows/{id}/schedules for creation/listing (mirrors
/workflows/{id}/run), flat /schedules/{id} for update/delete/get -
same nested-create + flat-mutate shape as /skills vs /skills/assign."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.schedule.service import WorkflowScheduleService
from app.schemas.common import PaginatedResponse
from app.schemas.workflow_schedule import WorkflowScheduleCreate, WorkflowScheduleRead, WorkflowScheduleUpdate

router = APIRouter(tags=["Workflow Scheduling (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_WORKFLOW_SCHEDULING:
        raise NotFoundError("Workflow Scheduling is not enabled on this deployment")


@router.post("/workflows/{workflow_id}/schedules", response_model=WorkflowScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(workflow_id: UUID, payload: WorkflowScheduleCreate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowScheduleService(db)
    obj = await service.create(workflow_id, payload)
    return WorkflowScheduleRead.model_validate(obj)


@router.get("/workflows/{workflow_id}/schedules", response_model=PaginatedResponse[WorkflowScheduleRead])
async def list_schedules(
    workflow_id: UUID, pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)
):
    _require_enabled()
    service = WorkflowScheduleService(db)
    items, total = await service.list_for_workflow(workflow_id, offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[WorkflowScheduleRead](
        items=[WorkflowScheduleRead.model_validate(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/schedules/{schedule_id}", response_model=WorkflowScheduleRead)
async def get_schedule(schedule_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowScheduleService(db)
    obj = await service.get(schedule_id)
    return WorkflowScheduleRead.model_validate(obj)


@router.put("/schedules/{schedule_id}", response_model=WorkflowScheduleRead)
async def update_schedule(schedule_id: UUID, payload: WorkflowScheduleUpdate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowScheduleService(db)
    obj = await service.update(schedule_id, payload)
    return WorkflowScheduleRead.model_validate(obj)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowScheduleService(db)
    await service.delete(schedule_id)


@router.post("/schedules/{schedule_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_schedule_now(schedule_id: UUID, db: AsyncSession = Depends(get_db)):
    """Fires the schedule immediately, bypassing next_run_at - useful
    for testing a schedule's configuration. Still advances next_run_at
    afterward via record_fired(), same as a real tick would."""
    _require_enabled()
    from app.schemas.workflow_run import WorkflowRunRequest
    from app.services.workflow_execution_service import WorkflowExecutionService

    service = WorkflowScheduleService(db)
    schedule = await service.get(schedule_id)

    exec_service = WorkflowExecutionService(db)
    result = await exec_service.run_workflow(
        schedule.workflow_id, WorkflowRunRequest(input=schedule.input_template, user_id=schedule.user_id)
    )
    await service.record_fired(schedule, status=result["status"], workflow_run_id=result["workflowRunId"])
    return {"workflowRunId": str(result["workflowRunId"]), "status": result["status"]}