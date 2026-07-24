"""
WorkflowWebhookService.

Metadata CRUD + the actual trigger path used by
POST /api/v1/webhooks/{token}. Signature verification and input
extraction live here (pure functions, easily unit-testable) - the API
route stays a thin "parse request -> call service" layer, per project
convention.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.workflow_webhook import WorkflowWebhook
from app.repositories.workflow_repository import WorkflowRepository
from app.repositories.workflow_webhook_repository import WorkflowWebhookRepository
from app.schemas.workflow_run import WorkflowRunRequest
from app.schemas.workflow_webhook import WorkflowWebhookCreate, WorkflowWebhookUpdate
from app.services.workflow_execution_service import WorkflowExecutionService

logger = get_logger(__name__)


def _generate_token() -> str:
    return secrets.token_urlsafe(24)


def verify_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 verification, same scheme as
    GitHub/Stripe webhooks: signature_header must equal
    hex(hmac_sha256(secret, raw_body))."""
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def extract_input(body: dict, field_path: str | None) -> str:
    """Resolves `field_path` (dotted, e.g. 'data.message') against the
    parsed JSON body. Falls back to the stringified whole body when
    field_path is unset or the path doesn't resolve to a scalar -
    never raises, since a webhook misconfiguration should degrade
    gracefully rather than reject a legitimate external call."""
    if not field_path:
        return json.dumps(body, ensure_ascii=False)

    node = body
    for part in field_path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return json.dumps(body, ensure_ascii=False)

    if isinstance(node, (dict, list)):
        return json.dumps(node, ensure_ascii=False)
    return str(node)


class WorkflowWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.webhook_repo = WorkflowWebhookRepository(session)
        self.workflow_repo = WorkflowRepository(session)

    async def create(self, workflow_id: uuid.UUID, payload: WorkflowWebhookCreate) -> WorkflowWebhook:
        workflow = await self.workflow_repo.get(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        webhook = await self.webhook_repo.create(
            workflow_id=workflow_id,
            webhook_token=_generate_token(),
            **payload.model_dump(),
        )
        logger.info("workflow_webhook_created", webhook_id=str(webhook.id), workflow_id=str(workflow_id))
        return webhook

    async def update(self, webhook_id: uuid.UUID, payload: WorkflowWebhookUpdate) -> WorkflowWebhook:
        webhook = await self.webhook_repo.get_or_404(webhook_id)
        return await self.webhook_repo.update(webhook, **payload.model_dump(exclude_unset=True))

    async def list_for_workflow(self, workflow_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.webhook_repo.list_by_workflow(workflow_id, offset=offset, limit=limit)

    async def delete(self, webhook_id: uuid.UUID) -> None:
        webhook = await self.webhook_repo.get_or_404(webhook_id)
        await self.webhook_repo.soft_delete(webhook)

    async def trigger(
        self,
        token: str,
        *,
        raw_body: bytes,
        source_ip: str | None,
        signature_header: str | None,
    ) -> dict:
        webhook = await self.webhook_repo.get_by_token(token)
        if webhook is None or not webhook.enabled:
            raise NotFoundError("Webhook not found or disabled")

        if webhook.allowed_source_ips and source_ip not in webhook.allowed_source_ips:
            raise ValidationFailedError("Source IP not allowed for this webhook")

        if webhook.secret and not verify_signature(webhook.secret, raw_body, signature_header):
            raise ValidationFailedError("Invalid or missing webhook signature")

        try:
            body = json.loads(raw_body or b"{}")
        except (TypeError, ValueError):
            body = {}
        if not isinstance(body, dict):
            body = {"value": body}

        input_text = extract_input(body, webhook.input_field_path)

        exec_service = WorkflowExecutionService(self.session)
        result = await exec_service.run_workflow(
            webhook.workflow_id,
            WorkflowRunRequest(input=input_text, user_id=webhook.user_id),
        )
        logger.info("workflow_webhook_triggered", webhook_id=str(webhook.id), status=result["status"])
        return result