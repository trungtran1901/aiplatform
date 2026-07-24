from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.workflow_webhook import WorkflowWebhook
from app.repositories.base import BaseRepository


class WorkflowWebhookRepository(BaseRepository[WorkflowWebhook]):
    model = WorkflowWebhook

    async def get_by_token(self, token: str) -> WorkflowWebhook | None:
        stmt = select(WorkflowWebhook).where(
            WorkflowWebhook.webhook_token == token,
            WorkflowWebhook.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_workflow(self, workflow_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, workflow_id=workflow_id)