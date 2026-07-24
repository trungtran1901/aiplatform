"""Workflow Webhooks - lets an external HTTP caller trigger a Workflow
run via a stable, opaque URL (`webhook_token`), independent of the
Workflow's own id/code so the URL survives Workflow edits.

AUTH NOTE (departure from the rest of this codebase's "never
authenticate" stance): a webhook call has no inbound end-user identity
to propagate the way /chat does (see app/core/auth_context.py). Two
independent, optional layers are provided instead:
  - `secret`: HMAC-SHA256 verification of the raw request body against
    an `X-Webhook-Signature` header, same pattern as GitHub/Stripe
    webhooks - proves the caller knows the shared secret, nothing more.
  - `allowed_source_ips`: optional IP allowlist.
Neither is authorization in the RBAC sense - this remains entirely out
of scope for this runtime (see docs/Architecture.md#1). If the
triggered Workflow's steps need real MCP Gateway credentials, `user_id`
here represents a fixed service-account identity, not a per-request
caller.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowWebhook(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "workflow_webhooks"
    __table_args__ = (UniqueConstraint("webhook_token", name="uq_workflow_webhook_token"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    webhook_token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSONPath-like dotted key (e.g. "message" or "data.text") applied to
    # the inbound JSON body to extract the workflow's `input` string.
    # None => the entire raw JSON body (stringified) is used as input.
    input_field_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    allowed_source_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    workflow: Mapped["Workflow"] = relationship()

    def __repr__(self) -> str:
        return f"<WorkflowWebhook token={self.webhook_token} workflow_id={self.workflow_id}>"