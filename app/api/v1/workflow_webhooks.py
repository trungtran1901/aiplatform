"""Workflow Webhook API - flagged behind FEATURE_WORKFLOW_WEBHOOKS.
The management endpoints (create/list/update/delete) live under
/api/v1, same as everything else. The actual public trigger endpoint
(POST /webhooks/{token}) is intentionally registered WITHOUT the
/api/v1 prefix's usual conventions getting in the way of a short,
stable external URL - see router wiring in app/api/v1/router.py."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.schemas.common import PaginatedResponse
from app.schemas.workflow_webhook import WorkflowWebhookCreate, WorkflowWebhookRead, WorkflowWebhookUpdate
from app.webhooks.service import WorkflowWebhookService

router = APIRouter(tags=["Workflow Webhooks (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_WORKFLOW_WEBHOOKS:
        raise NotFoundError("Workflow Webhooks is not enabled on this deployment")


def _to_read(obj) -> WorkflowWebhookRead:
    data = {
        "id": obj.id, "created_at": obj.created_at, "updated_at": obj.updated_at,
        "workflow_id": obj.workflow_id, "webhook_token": obj.webhook_token,
        "input_field_path": obj.input_field_path, "allowed_source_ips": obj.allowed_source_ips,
        "user_id": obj.user_id, "enabled": obj.enabled,
        "invoke_path": f"/webhooks/{obj.webhook_token}",
    }
    return WorkflowWebhookRead.model_validate(data)


@router.post("/workflows/{workflow_id}/webhooks", response_model=WorkflowWebhookRead, status_code=status.HTTP_201_CREATED)
async def create_webhook(workflow_id: UUID, payload: WorkflowWebhookCreate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowWebhookService(db)
    obj = await service.create(workflow_id, payload)
    return _to_read(obj)


@router.get("/workflows/{workflow_id}/webhooks", response_model=PaginatedResponse[WorkflowWebhookRead])
async def list_webhooks(workflow_id: UUID, pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowWebhookService(db)
    items, total = await service.list_for_workflow(workflow_id, offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[WorkflowWebhookRead](
        items=[_to_read(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.put("/webhooks/{webhook_id}", response_model=WorkflowWebhookRead)
async def update_webhook(webhook_id: UUID, payload: WorkflowWebhookUpdate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowWebhookService(db)
    obj = await service.update(webhook_id, payload)
    return _to_read(obj)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    service = WorkflowWebhookService(db)
    await service.delete(webhook_id)


# --- Public trigger endpoint, called by external systems ---
@router.post("/webhooks/{token}/invoke", status_code=status.HTTP_202_ACCEPTED)
async def invoke_webhook(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """External callers POST here to trigger the associated Workflow.
    No FastAPI/Pydantic body model is used deliberately - the raw bytes
    are needed unmodified for HMAC signature verification before JSON
    parsing happens inside the service layer."""
    _require_enabled()
    raw_body = await request.body()
    service = WorkflowWebhookService(db)
    result = await service.trigger(
        token,
        raw_body=raw_body,
        source_ip=request.client.host if request.client else None,
        signature_header=request.headers.get("X-Webhook-Signature"),
    )
    return {"workflowRunId": str(result["workflowRunId"]), "status": result["status"]}