"""
Quota Management - per-user / per-group usage limits, enforced against
Keycloak-verified identity (app.core.identity).

Two tables, deliberately split like the rest of this codebase's
metadata-vs-audit pattern (see e.g. Workflow vs WorkflowRun):

  QuotaPolicy      - metadata: WHAT limit applies to WHICH scope.
                      Soft-deleted like every other metadata table.
  QuotaUsageEvent   - append-only audit trail: WHAT was actually
                      consumed, per run. Never deleted - this is the
                      durable record reconciled against your billing
                      gateway and used to rebuild Redis counters if
                      Redis data is ever lost (see
                      app/services/quota_service.py).

Real-time enforcement itself does NOT query these tables on the hot
path - it reads a Redis counter (app/services/quota_service.py) for
low latency. QuotaUsageEvent is written asynchronously-in-request
(after the run completes) as the durable source of truth.
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class QuotaScopeType(str, Enum):
    global_ = "GLOBAL"  # applies to every user/group not otherwise covered
    group = "GROUP"      # scope_value = Keycloak group name (from JWT "groups" claim)
    user = "USER"        # scope_value = Keycloak "sub" (verified user id)


class QuotaPeriod(str, Enum):
    daily = "DAILY"
    monthly = "MONTHLY"
    fixed_window = "FIXED_WINDOW"  # window_seconds defines the rolling/fixed bucket size


class QuotaMetric(str, Enum):
    requests = "REQUESTS"
    tokens = "TOKENS"       # input_tokens + output_tokens combined
    cost_usd = "COST_USD"   # requires ModelRegistry cost fields to be populated


class QuotaPolicy(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One limit rule. Resolution order (most specific wins - see
    QuotaService.resolve_effective_policy): USER > GROUP > GLOBAL.
    Multiple GROUP policies can match one caller (a user can belong to
    several Keycloak groups); `priority` (higher wins) breaks ties.

    `model_id=None` means the policy applies across ALL models - useful
    for "user X gets 100k tokens/day total regardless of which model
    they call," separate from any per-model policy that might also
    exist for the same scope.
    """

    __tablename__ = "quota_policies"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_value", "model_id", "metric", "period",
            name="uq_quota_policy_scope",
        ),
    )

    scope_type: Mapped[QuotaScopeType] = mapped_column(
        SAEnum(QuotaScopeType, name="quota_scope_type", values_callable=lambda o: [e.value for e in o]),
        nullable=False, index=True,
    )
    # "" for GLOBAL scope; Keycloak group name for GROUP; verified sub for USER.
    scope_value: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)

    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_registry.id", ondelete="CASCADE"), nullable=True, index=True
    )

    metric: Mapped[QuotaMetric] = mapped_column(
        SAEnum(QuotaMetric, name="quota_metric", values_callable=lambda o: [e.value for e in o]), nullable=False
    )
    period: Mapped[QuotaPeriod] = mapped_column(
        SAEnum(QuotaPeriod, name="quota_period", values_callable=lambda o: [e.value for e in o]), nullable=False
    )
    # Only used when period=FIXED_WINDOW - the bucket width in seconds.
    window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    limit_value: Mapped[int] = mapped_column(
        Integer, nullable=False,
        doc="Integer limit for the metric+period (tokens count, request count, or cost*100 as cents).",
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)

    model: Mapped["ModelRegistry"] = relationship(foreign_keys=[model_id])

    def __repr__(self) -> str:
        return (
            f"<QuotaPolicy {self.scope_type}:{self.scope_value} "
            f"metric={self.metric} period={self.period} limit={self.limit_value}>"
        )


class QuotaUsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per completed AgentRun/WorkflowRun that consumed quota.
    Append-only - same audit philosophy as agent_events/runtime_observations.
    `run_id` is unique-ish per write path (idempotency is enforced at
    the service layer, not a DB constraint, since a run may legitimately
    have zero usage events if it failed before producing any tokens)."""

    __tablename__ = "quota_usage_events"

    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Snapshot of the caller's Keycloak groups AT THE TIME of the run,
    # so historical usage events remain accurate even if group
    # membership changes later.
    groups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_registry.id", ondelete="SET NULL"), nullable=True, index=True
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    model: Mapped["ModelRegistry"] = relationship(foreign_keys=[model_id])

    def __repr__(self) -> str:
        return f"<QuotaUsageEvent user_id={self.user_id} run_id={self.run_id} tokens={self.input_tokens + self.output_tokens}>"