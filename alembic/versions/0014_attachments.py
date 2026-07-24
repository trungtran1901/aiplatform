"""add attachments table (file upload + OCR/extraction registry)

Revision ID: 0014_attachments
Revises: 0013_execution_engine
Create Date: 2026-07-22

New, standalone append-mostly table for user-uploaded attachments
(image/pdf/docx/xlsx) - stores MinIO storage location + extracted text
(via OCR service or in-process parser) so chat-time context building
never re-runs extraction, only reads the stored extracted_text.

No FK to chat_sessions - session_id is loosely scoped (nullable, no FK
constraint), mirroring app.models.observation.RuntimeObservation's
rationale: an attachment can be uploaded before a session exists, and
must never be blocked by, or cascade-delete with, its session.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_attachments"
down_revision = "0013_execution_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    attachment_kind = postgresql.ENUM(
        "IMAGE", "PDF", "DOCX", "XLSX", "OTHER", name="attachment_kind", create_type=False
    )
    attachment_status = postgresql.ENUM(
        "UPLOADED", "PROCESSING", "READY", "FAILED", name="attachment_status", create_type=False
    )
    bind = op.get_bind()
    attachment_kind.create(bind, checkfirst=True)
    attachment_status.create(bind, checkfirst=True)

    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("kind", attachment_kind, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False),
        sa.Column("status", attachment_status, nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=True),
        sa.Column("extraction_raw", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_attachments_session_id", "attachments", ["session_id"])
    op.create_index("ix_attachments_user_id", "attachments", ["user_id"])
    op.create_index("ix_attachments_status", "attachments", ["status"])


def downgrade() -> None:
    op.drop_table("attachments")
    bind = op.get_bind()
    postgresql.ENUM(name="attachment_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="attachment_kind").drop(bind, checkfirst=True)