from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class WorkflowWebhookBase(BaseModel):
    input_field_path: str | None = Field(
        default=None, description="Dotted path into the inbound JSON body used as workflow input, "
        "e.g. 'data.message'. Omit to use the entire raw body (stringified)."
    )
    allowed_source_ips: list[str] | None = None
    user_id: str | None = None
    enabled: bool = True


class WorkflowWebhookCreate(WorkflowWebhookBase):
    secret: str | None = Field(default=None, description="Shared secret for HMAC-SHA256 request verification")


class WorkflowWebhookUpdate(BaseModel):
    secret: str | None = None
    input_field_path: str | None = None
    allowed_source_ips: list[str] | None = None
    user_id: str | None = None
    enabled: bool | None = None


class WorkflowWebhookRead(TimestampedSchema, WorkflowWebhookBase):
    workflow_id: UUID
    webhook_token: str
    # secret is intentionally never returned in read responses
    invoke_path: str = Field(description="Relative path external callers POST to")